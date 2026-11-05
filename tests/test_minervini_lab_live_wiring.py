"""B-1469: Minervini lab cells (pct8_hard exit + one feature filter, h30/h40) wired into the live swing scan.
Registry/gate/owner bar, signal = real VCP entry + feature filter, 8% hard stop on every trade, exit adapter, wiring."""
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

CELLS = main.MINERVINI_LAB_LIVE_CELLS


def _frame(n=300, end="2026-10-30"):
    rng = np.random.default_rng(1)
    c = 100 * np.exp(rng.normal(0.001, 0.01, n).cumsum())
    idx = pd.bdate_range(end=end, periods=n)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.full(n, 1e5)}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def test_registry_owner_bar_and_gate():
    names = {s.name: s for s in sr.REGISTRY}
    assert len(CELLS) == 28  # B-1471: 3 (pooled + OOS) + 25 on the pooled bar
    for t, (_f, _w, maxh) in CELLS.items():
        m = names[t].metrics
        assert m.pfnet > 1.0 and m.n_trades >= 30 and m.avg_held_bars <= 30, t
        assert t.replace("__v1", "_segoos__v1") in names, t  # OOS kept for the record; pooled decides (B-1471)
        assert f"__h{maxh}__" in t and main._strategy_hold_spec(t)[0] == maxh
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t and t not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is True
        assert "stopout_cluster" not in t and "rs_blend" not in t


def _fake_sig(stop=95.0):
    return lambda df, rs_percentile=None: {"entry_price": float(df["Close"].iloc[-1]), "stop_loss": stop, "atr_at_entry": 2.0}


def test_signal_filter_and_hard_stop(monkeypatch):
    df = _frame()
    px = float(df["Close"].iloc[-1])
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", _fake_sig(px * 0.95))
    t_up = "minervini_vcp__pct8_hard_f_updown_vol_pos_off_srcmain__long__1d__h30__v1"
    f = main.minervini_lab_features(df, len(df) - 1, None, None, False)
    sig = main.minervini_lab_live_entry_signal(df, t_up)
    if f["updown_vol_pos"]:
        assert sig is None
    else:
        assert sig["stop_loss"] == pytest.approx(px * 0.92) and 0 < sig["stop_loss"] < sig["entry_price"]
    monkeypatch.setattr(main, "minervini_lab_features", lambda *a: {"updown_vol_pos": False, "ext_le5": True})
    assert main.minervini_lab_live_entry_signal(df, t_up)["stop_loss"] == pytest.approx(px * 0.92)
    assert main.minervini_lab_live_entry_signal(df, "minervini_vcp__pct8_hard_f_ext_le5_off_srcmain__long__1d__h30__v1") is None
    # early_bull without an index fails closed
    monkeypatch.setitem(main._ONEIL_DAILY_IDX, "close", None)
    assert main.minervini_lab_live_entry_signal(df, "minervini_vcp__pct8_hard_f_early_bull_10_25_on_srcmain__long__1d__h40__v1") is None
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", _fake_sig(px * 1.01))  # structural stop above entry -> none
    assert main.minervini_lab_live_entry_signal(df, t_up) is None
    assert main.minervini_lab_live_entry_signal(df.iloc[:100], t_up) is None
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", lambda df, rs_percentile=None: None)
    assert main.minervini_lab_live_entry_signal(df, t_up) is None


def test_exit_adapter_stop_and_max_hold():
    t = "minervini_vcp__pct8_hard_f_updown_vol_pos_off_srcmain__long__1d__h30__v1"
    df = _frame()
    ed = df["Date"].iloc[-40]
    entry = float(df["Close"].iloc[-40])
    r, _ = main._minervini_lab_live_exit_adapter(df, ed, entry * 0.5, 1.0, 0.0, t)
    assert r == "minervini_lab_max_hold_timeout"
    r, _ = main._minervini_lab_live_exit_adapter(df, ed, entry * 5, 1.0, 0.0, t)
    assert r == "minervini_lab_stop_hit"
    assert main._minervini_lab_live_exit_adapter(df, df["Date"].iloc[-1], entry * 0.5, 1.0, 0.0, t)[0] is None
    short = main._minervini_lab_live_exit_adapter(df, df["Date"].iloc[-10], entry * 0.1, 1.0, 0.0, t)
    assert short[0] is None  # 9 bars held < 30


def test_scan_wiring_order_and_exit_branch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("_chan_kalman_1d_try_entry(conn") < src.index("_minervini_lab_live_try_entry(conn")
    assert 'pos["strategy"] in MINERVINI_LAB_LIVE_CELLS' in src
    ent = inspect.getsource(main._minervini_lab_live_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in ent
    assert "_is_strategy_wired(tag" in ent


def test_blocked_trigger_when_gate_closed(monkeypatch):
    main._strategy_blocked_triggers.clear()
    monkeypatch.setattr(main, "minervini_lab_live_entry_signal",
                        lambda df, t: {"entry_price": 10.0, "stop_loss": 9.2, "atr_at_entry": 0.25})
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t, check_switch=True: False)
    assert main._minervini_lab_live_try_entry(None, "X.NS", None, 1e5, 0.01, "2026-10-30", 1.0) is False
    assert sum(main._strategy_blocked_triggers.get(t, 0) for t in CELLS) == len(CELLS)
