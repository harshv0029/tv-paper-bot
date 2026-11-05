"""B-1471: brk20_min_rr LONG 1h atr4_rr4 wired into the swing engine's 1h leg on the pooled PFnet bar."""
import inspect

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

TAG = "brk20_min_rr__main_replay__long__1h__atr4_rr4__v1"


def _frame(n=120, jump=True):
    c = np.full(n, 100.0) + np.sin(np.arange(n)) * 0.5
    if jump:
        c[-1] = 104.0
    idx = pd.date_range("2026-10-01 03:45", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame({"Open": c, "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 1e5})
    df["Date"] = [str(t) for t in idx]
    return df


def test_registry_pooled_bar_and_mapping():
    m = {d.name: d for d in sr.REGISTRY}[TAG].metrics
    assert m.pfnet > 1.0 and m.n_trades >= 30
    assert main.BRK20_1H_LONG_CELLS[TAG] == (4.0, 4.0, 30)
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG] == TAG
    assert main._strategy_hold_spec(TAG) == (30, "1h")
    assert "EMA13" in main._SWING_SL_RULES[TAG]


def test_signal_matches_real_function_and_has_stop():
    df = _frame()
    real = main.brk20_min_rr_entry_signal(df, "long", atr_mult=4.0, min_rr=4.0)
    sig = main.brk20_1h_long_entry_signal(df, TAG)
    if real is None:
        assert sig is None
    else:
        assert sig["stop_loss"] == real["stop_loss"] and 0 < sig["stop_loss"] < sig["entry_price"]
    assert main.brk20_1h_long_entry_signal(df, "nope") is None


def test_exit_stop_hit_after_fill():
    df = _frame(jump=False)
    pos = {"strategy": TAG, "entry_day": df["Date"].iloc[-5], "entry_price": 100.0, "initial_stop_loss": 99.9}
    r = main._brk20_long_1h_exit(df, pos)
    assert r is not None and r[0] == "brk20_stop_loss"
    pos["entry_day"] = df["Date"].iloc[-1]
    assert main._brk20_long_1h_exit(df, pos) is None  # no bar after the signal bar yet


def test_wired_in_1h_leg():
    src = inspect.getsource(main._run_long_swing_1h_pass)
    assert "_brk20_long_1h_try_entry(conn, symbol, df, capital" in src and "_brk20_long_1h_exit(df, pos)" in src
    assert "BRK20_1H_LONG_CELLS" in inspect.getsource(main._with_held_1h_long_symbols)
    assert "BRK20_1H_LONG_CELLS" in inspect.getsource(main._scan_only_1h_long_cells)
