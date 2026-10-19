"""B-983: pl1d LONG 1d cells (starc fade full-universe, gap runaway) swing-engine port + gate wiring."""
import inspect
import sys

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

_REG = {d.name: d for d in sr.REGISTRY}


def _daily(o, h, l, c):
    n = len(c)
    return pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
                         "Open": np.asarray(o, float), "High": np.asarray(h, float), "Low": np.asarray(l, float),
                         "Close": np.asarray(c, float), "Volume": 1e6})


def _flat(n=80, px=100.0, spread=1.0):
    c = np.full(n, px)
    return c.copy(), c + spread, c - spread, c.copy()


def _starc_df():
    o, h, l, c = _flat()
    c[-1] = 90.0  # far below SMA6 - 2 x ATR15 (~100 - 2 x ~2)
    o[-1], h[-1], l[-1] = 100.0, 100.0, 89.0
    return _daily(o, h, l, c)


def _gap_df():
    o, h, l, c = _flat()
    o[-1], h[-1], l[-1], c[-1] = 102.5, 105.0, 102.0, 104.0  # open > prior high (101) x 1.01, close > open, > SMA50
    return _daily(o, h, l, c)


def test_cells_map_one_to_one_owed_and_gate_closed():
    assert set(main.PL1D_CELLS) == {main.STARC_FULL_TAG, main.GAP_RUNAWAY_TAG}
    for t in main.PL1D_CELLS:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t in _REG and _REG[t].metrics is not None and "__long__" in t
        assert "atrnone" not in t
        # B-1233: run 38506928246 (main.py-calling replay, PFnet 1.20/1.22, n > 9000) is on file -> owed flag cleared, gate derives open
        assert t not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is True
    assert _REG[main.STARC_FULL_TAG].metrics.pfnet >= sr.PFNET_LIVE_FLOOR
    assert _REG[main.GAP_RUNAWAY_TAG].metrics.pfnet >= sr.PFNET_LIVE_FLOOR


def test_starc_signal_rule_and_stop():
    df = _starc_df()
    sig = main.pl1d_long_entry_signal(df, main.STARC_FULL_TAG)
    assert sig and sig["entry_price"] == 90.0 and 0 < sig["stop_loss"] < 90.0
    atr = main.chan_atr14(df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy())[-1]
    assert abs(sig["stop_loss"] - (90.0 - 2.5 * atr)) < 1e-9
    o, h, l, c = _flat()
    assert main.pl1d_long_entry_signal(_daily(o, h, l, c), main.STARC_FULL_TAG) is None
    assert main.pl1d_long_entry_signal(df, "starc__nope") is None
    assert main.pl1d_long_entry_signal(df.iloc[:30], main.STARC_FULL_TAG) is None


def test_gap_runaway_signal_rule_and_stop():
    df = _gap_df()
    sig = main.pl1d_long_entry_signal(df, main.GAP_RUNAWAY_TAG)
    assert sig and sig["entry_price"] == 104.0 and 0 < sig["stop_loss"] < 104.0
    assert main.pl1d_long_entry_signal(_starc_df(), main.GAP_RUNAWAY_TAG) is None
    d2 = df.copy()
    d2.loc[d2.index[-1], "Close"] = 102.0  # close < open: runaway fails
    assert main.pl1d_long_entry_signal(d2, main.GAP_RUNAWAY_TAG) is None


def test_exit_stop_gap_aware_then_hold():
    o, h, l, c = _flat(12)
    df = _daily(o, h, l, c)
    entry_day = df["Date"].iloc[5]
    assert main.pl1d_exit_reason(df.iloc[:6], entry_day, 90.0, 5) == (None, None)
    assert main.pl1d_exit_reason(df.iloc[:10], entry_day, 90.0, 5) == (None, None)
    assert main.pl1d_exit_reason(df.iloc[:11], entry_day, 90.0, 5) == ("pl1d_max_hold_timeout", 100.0)
    d2 = df.copy()
    d2.loc[7, ["Low", "Open"]] = [85.0, 99.0]
    assert main.pl1d_exit_reason(d2.iloc[:9], entry_day, 90.0, 5) == ("pl1d_stop_loss", 90.0)
    d2.loc[7, "Open"] = 80.0
    assert main.pl1d_exit_reason(d2.iloc[:9], entry_day, 90.0, 5) == ("pl1d_stop_loss", 80.0)


def test_wiring_sources_present():
    scan = inspect.getsource(main._run_swing_scan_pass)
    assert "_pl1d_try_entry" in scan and "PL1D_CELLS" in scan
    assert scan.index("_chan_shape_try_entry") < scan.index("_pl1d_try_entry")  # appended after the existing chain
    src = inspect.getsource(main._pl1d_try_entry)
    assert ("_is_strategy_viable_for_real_money" in src or "_is_strategy_wired" in src) and "_maybe_place_real_swing_entry" in src
    assert "stop_loss" in src and "atr_at_entry" in src
    real = inspect.getsource(main._maybe_place_real_swing_entry)
    assert "_load_viable_overrides()" in real and "entry_sl_failed_unwind" in real  # B-962 re-check + B-966 unwind
    assert "reason=" in real


def test_replay_driver_calls_real_main_functions_and_smoke():
    src = open("scripts/pl1d_main_replay.py").read()
    for fn in ("m.pl1d_long_entry_signal", "m.pl1d_exit_reason", "_load_nse_universe_from_file", "load_frames"):
        assert fn in src or fn in open("scripts/chan_shape_macddiv_main_replay.py").read()
    assert "m.NSE_FULL_UNIVERSE" not in src
    sys.path.insert(0, "scripts")
    import pl1d_main_replay as rp
    import chan_shape_macddiv_main_replay as base
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    res = rp.replay_symbol(main, base.synthetic_frame(1), list(main.PL1D_CELLS), cost)
    assert set(res) == set(main.PL1D_CELLS)
    for trs in res.values():  # strict FIFO
        for a, b in zip(trs, trs[1:]):
            assert b["entry_i"] > a["exit_i"]
