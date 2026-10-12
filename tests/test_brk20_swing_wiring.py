"""B-798: brk20_min_rr LONG 1d atr4_rr4 live swing wiring (no new kill switch, PFnet-gated, SL with entry)."""
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

TAG = main.BRK20_SWING_TAG


def _frame(close, high=None, low=None, open_=None, start="2024-01-01"):
    close = np.asarray(close, float)
    o = close.copy() if open_ is None else np.asarray(open_, float)
    h = np.maximum(close, o) + 0.3 if high is None else np.asarray(high, float)
    l = np.minimum(close, o) - 0.3 if low is None else np.asarray(low, float)
    idx = pd.bdate_range(start, periods=len(close))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": close, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _breakout(n=100):
    c = np.full(n, 100.0)
    c[-1] = 101.0
    h = c + 0.3
    h[40] = 140.0
    return _frame(c, high=h)


def test_tag_grammar_and_registry_mapping():
    assert TAG == "brk20_min_rr__main_replay__long__1d__atr4_rr4__v1"
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG] == TAG
    assert main.BRK20_SWING_ATR_MULT == 4.0 and main.BRK20_SWING_MIN_RR == 4.0


def test_gate_opens_only_if_viable(monkeypatch):
    strat = next(s for s in sr.REGISTRY if s.name == TAG)
    assert strat.metrics.pfnet >= sr.PFNET_LIVE_FLOOR >= 1.1
    assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is True
    orig = strat.metrics
    import dataclasses
    object.__setattr__(strat, "metrics", dataclasses.replace(orig, pfnet=1.05))  # below the 1.1 floor
    try:
        assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is False
    finally:
        object.__setattr__(strat, "metrics", orig)


def test_entry_fires_with_atr_stop_attached():
    sig = main.brk20_min_rr_entry_signal(_breakout(), "long", main.BRK20_SWING_ATR_MULT, main.BRK20_SWING_MIN_RR)
    assert sig is not None
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 4.0 * sig["atr_at_entry"])
    assert 0 < sig["stop_loss"] < sig["entry_price"]


def test_scan_chain_order_and_stop_is_real_sl():
    src = inspect.getsource(main._run_swing_scan_pass)
    i_ob = src.index("SWING_EXITINVAL_OB_TAG, order_block_entry_signal")
    i_b = src.index('brk20_min_rr_entry_signal(df, "long"')
    assert i_b > i_ob  # checked after the existing setups
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, BRK20_SWING_TAG)" in src
    assert '_bs["stop_loss"]' in src
    assert "_brk20_swing_exit_adapter" in src
    assert "_maybe_place_real_swing_exit(conn, symbol, reason=" in src  # reason logged on exit


def test_exit_adapter_stop_rule_and_timeout():
    atr, entry = 1.0, 100.0
    stop = entry - 4 * atr
    n = 100
    base = _frame(np.full(n, 100.0))
    entry_day = base["Date"].iloc[-1]
    r, _ = main._brk20_swing_exit_adapter(base, entry_day, stop, atr, entry)
    assert r is None
    nxt = _frame(np.full(n + 1, 100.0))
    lo = nxt["Low"].to_numpy().copy()
    lo[-1] = 90.0
    nxt = nxt.assign(Low=lo)
    r, _ = main._brk20_swing_exit_adapter(nxt, entry_day, stop, atr, entry)
    assert r == "stop_loss"
    # fill bar = n (first bar after entry day); timeout at fill + 30 even if intermediate scans were missed
    drift = _frame(np.full(n + 31, 100.0))
    r, _ = main._brk20_swing_exit_adapter(drift, entry_day, stop, atr, entry)
    assert r == "max_hold_timeout"
    drift_short = _frame(np.full(n + 30, 100.0))
    r, _ = main._brk20_swing_exit_adapter(drift_short, entry_day, stop, atr, entry)
    assert r is None


def test_exit_adapter_rule_exit_when_close_below_falling_ema():
    n = 100
    c = np.full(n + 6, 100.0)
    c[n:] = [99, 97, 95, 93, 92, 91]
    df = _frame(c, high=c + 0.3, low=c - 0.3)
    entry_day = df["Date"].iloc[n - 1]
    r, _ = main._brk20_swing_exit_adapter(df, entry_day, 80.0, 5.0, 100.0)
    assert r == "rule_exit"


def test_sl_rule_listed_for_dashboard():
    assert TAG in main._SWING_SL_RULES
