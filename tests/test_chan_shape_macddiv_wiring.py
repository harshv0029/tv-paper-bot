"""B-965: chan_shape LONG 1d (swing engine) and macddiv LONG 1h (replay-only) ports + gate wiring."""
import inspect
import re

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

_REG = {d.name: d for d in sr.REGISTRY}


def _daily(closes, spread=1.0):
    n = len(closes)
    c = np.asarray(closes, float)
    return pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
                         "Open": c, "High": c + spread, "Low": c - spread, "Close": c, "Volume": 1e6})


def _shape_df():
    # close[-1]=100 < close[-31]=110 and > close[-41]=90
    c = np.full(60, 100.0)
    c[-31], c[-41] = 110.0, 90.0
    return _daily(c)


def test_cells_map_one_to_one_to_registry_rows_and_are_owed():
    assert len(main.CHAN_SHAPE_CELLS) == 6 and len(main.MACDDIV_LONG_CELLS) == 4
    for t in list(main.CHAN_SHAPE_CELLS) + list(main.MACDDIV_LONG_CELLS):
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t in _REG and _REG[t].metrics is not None
        assert "__long__" in t
        assert t in main.REPLAY_OWED_TAGS or t in main.REPLAY_FAILED_TAGS  # B-1396: owed, or replayed below floor
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False


def test_year_slice_tags_are_not_wired():
    for t in _REG:
        if t.startswith("chan_shape__") and re.search(r"_y20\d\d__", t):
            assert t not in main._STRATEGY_TAG_TO_REGISTRY_NAME


def test_chan_shape_signal_has_stop_and_exact_rule():
    df = _shape_df()
    tag = main._chan_shape_cell_tag(2.5, 5)
    sig = main.chan_shape_long_entry_signal(df, tag)
    c = df["Close"].to_numpy()
    assert (c[-1] < c[-31] and c[-1] > c[-41]) == bool(sig)
    assert sig and 0 < sig["stop_loss"] < sig["entry_price"] == c[-1]
    atr = main.chan_atr14(df["High"].to_numpy(), df["Low"].to_numpy(), c)[-1]
    assert abs(sig["stop_loss"] - (c[-1] - 2.5 * atr)) < 1e-9
    assert main.chan_shape_long_entry_signal(df, "chan_shape__nope") is None
    up = _daily(np.linspace(50, 150, 80))  # close above both lookbacks: no signal
    assert main.chan_shape_long_entry_signal(up, tag) is None


def test_chan_shape_exit_stop_then_hold():
    df = _daily(np.full(12, 100.0), spread=1.0)
    entry_day = df["Date"].iloc[5]
    assert main.chan_shape_exit_reason(df.iloc[:6], entry_day, 90.0, 5) == (None, None)
    r, px = main.chan_shape_exit_reason(df.iloc[:10], entry_day, 90.0, 5)  # bars 6..9 = 4 bars < 5
    assert r is None
    r, px = main.chan_shape_exit_reason(df.iloc[:11], entry_day, 90.0, 5)  # 5th bar after entry
    assert (r, px) == ("chan_shape_max_hold_timeout", 100.0)
    d2 = df.copy()
    d2.loc[7, ["Low", "Open"]] = [85.0, 99.0]
    r, px = main.chan_shape_exit_reason(d2.iloc[:9], entry_day, 90.0, 5)
    assert (r, px) == ("chan_shape_stop_loss", 90.0)  # stop beats open when open > stop (no gap)
    d2.loc[7, "Open"] = 80.0
    r, px = main.chan_shape_exit_reason(d2.iloc[:9], entry_day, 90.0, 5)
    assert (r, px) == ("chan_shape_stop_loss", 80.0)  # gap-aware


def test_macddiv_exit_and_cells():
    n = 40
    c = np.full(n, 100.0)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c})
    assert main.macddiv_long_exit_reason(df.iloc[:20], 10, 90.0) == (None, None)
    r, px = main.macddiv_long_exit_reason(df, 5, 90.0)
    assert r == "macddiv_max_hold_timeout" and px == 100.0
    df.loc[8, "Low"] = 80.0
    assert main.macddiv_long_exit_reason(df, 5, 90.0) == ("macddiv_stop_loss", 90.0)
    assert main.macddiv_long_cell_signal(df, "nope") is None


def test_wiring_sources_present_and_macddiv_in_swing_1h_pass():
    scan = inspect.getsource(main._run_swing_scan_pass)
    assert "_chan_shape_try_entry" in scan and "CHAN_SHAPE_CELLS" in scan
    # B-984: macddiv holds overnight (CNC long) so the swing engine owns it, via the 1h pass (daily pass only skips it)
    assert "_run_long_swing_1h_pass" in scan and "MACDDIV_LONG_LIVE_CELLS" in scan
    one_h = inspect.getsource(main._macddiv_long_1h_try_entry)
    assert "_is_strategy_wired" in one_h and "_maybe_place_real_swing_entry" in one_h
    assert "stop_loss" in one_h and "macddiv_long_cell_signal" in one_h
    assert "_hourly_with_str_date" in inspect.getsource(main._run_long_swing_1h_pass)
    src = inspect.getsource(main._chan_shape_try_entry)
    assert ("_is_strategy_viable_for_real_money" in src or "_is_strategy_wired" in src) and "_maybe_place_real_swing_entry" in src
    real = inspect.getsource(main._maybe_place_real_swing_entry)
    assert "_load_viable_overrides()" in real and "entry_sl_failed_unwind" in real  # B-962 re-check + B-966 unwind
    assert "reason=" in real


def test_replay_driver_calls_real_main_functions():
    src = open("scripts/chan_shape_macddiv_main_replay.py").read()
    for fn in ("m.chan_shape_long_entry_signal", "m.chan_shape_exit_reason", "m.macddiv_long_cell_signal",
               "m.macddiv_long_exit_reason", "_load_nse_universe_from_file"):
        assert fn in src
    assert "m.NSE_FULL_UNIVERSE" not in src


def test_replay_driver_synthetic_smoke(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import chan_shape_macddiv_main_replay as rp
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    df = rp.synthetic_frame(1)
    res = rp.replay_symbol(main, df, "chan_shape", list(main.CHAN_SHAPE_CELLS), cost)
    assert set(res) == set(main.CHAN_SHAPE_CELLS) and sum(len(v) for v in res.values()) > 0
    for trs in res.values():  # strict FIFO: each entry after the previous exit
        for a, b in zip(trs, trs[1:]):
            assert b["entry_i"] > a["exit_i"]
    res = rp.replay_symbol(main, df, "macddiv", list(main.MACDDIV_LONG_CELLS), cost)
    assert set(res) == set(main.MACDDIV_LONG_CELLS)


def test_macddiv_live_cells_are_nonovl_line_only_and_gate_closed():
    assert set(main.MACDDIV_LONG_LIVE_CELLS) <= set(main.MACDDIV_LONG_CELLS)
    assert len(main.MACDDIV_LONG_LIVE_CELLS) == 4
    assert all(("line_any" in t or "hist_any" in t) and "nonovl" in t and "segis" not in t for t in main.MACDDIV_LONG_LIVE_CELLS)
    assert all(t in main.REPLAY_OWED_TAGS or t in main.REPLAY_FAILED_TAGS or t in main._replay_verified_tags()
               for t in main.MACDDIV_LONG_LIVE_CELLS)
    assert all(main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t for t in main.MACDDIV_LONG_LIVE_CELLS)


def test_macddiv_1h_exit_uses_fill_bar_after_entry():
    import numpy as np
    n = 40
    df = pd.DataFrame({"Date": [f"2026-01-01 {9 + i % 7:02d}:15" if False else f"2026-01-{1 + i // 7:02d} {9 + i % 7:02d}:15" for i in range(n)],
                       "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0})
    pos = {"entry_day": df["Date"].iloc[5], "initial_stop_loss": 90.0}
    assert main._macddiv_long_1h_exit(df.iloc[:20], pos) is None
    r = main._macddiv_long_1h_exit(df, pos)
    assert r == ("macddiv_max_hold_timeout", 100.0)
