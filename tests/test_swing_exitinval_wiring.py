import numpy as np
import pandas as pd
import pytest

import main

VP = main.SWING_EXITINVAL_VP_TAG
OB = main.SWING_EXITINVAL_OB_TAG


def _bars(closes, start="2024-01-01", spread=0.5):
    """Business-day bars; Open=prev close, High/Low = close +/- spread."""
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) + spread, "Low": np.minimum(o, c) - spread,
                       "Close": c, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def test_tags_exact_and_registered_to_themselves():
    assert VP == "volume_profile_poc__exitinval__long__1d__atr6d0_hold30_sigema13w__v1"
    assert OB == "order_block_delta__exitinval__long__1d__atr6d0_hold30_sigema13w__v1"
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[VP] == VP
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[OB] == OB
    # legacy tags still recognised for already-open positions
    assert "order_block_delta" in main._STRATEGY_TAG_TO_REGISTRY_NAME
    assert "volume_profile_poc" in main._STRATEGY_TAG_TO_REGISTRY_NAME


def test_stop_is_entry_minus_6_atr():
    assert main.swing_exitinval_stop(100.0, 2.5) == pytest.approx(85.0)
    assert main.SWING_EXITINVAL_ATR_MULT == 6.0
    # stop never trails for the new tags
    assert main._swing_strategy_stop_level(VP, 85.0, 2.5, 150.0) == 85.0
    assert main._swing_strategy_stop_level(OB, 85.0, 2.5, 150.0) == 85.0
    # legacy tags still trail
    assert main._swing_strategy_stop_level("volume_profile_poc", 85.0, 2.5, 150.0) > 85.0


def test_dispatch_new_vs_old_tags():
    assert main.swing_obvp_exit_fn(VP) is main._swing_exitinval_adapter
    assert main.swing_obvp_exit_fn(OB) is main._swing_exitinval_adapter
    assert main.swing_obvp_exit_fn("order_block_delta") is main.order_block_exit_reason
    assert main.swing_obvp_exit_fn("volume_profile_poc") is main.volume_profile_poc_exit_reason
    assert main.swing_obvp_exit_fn("gap_and_go") is None


def _flat_then(n_flat, tail):
    return [100.0] * n_flat + list(tail)


def test_stop_hit_intrabar_and_on_gap_open():
    base = _bars([100.0] * 40)
    entry_day = base["Date"].iloc[-1]
    # next bar low pierces stop (entry 100, atr 2 -> stop 88)
    nxt = _bars([100.0] * 41)
    nxt.iloc[-1, nxt.columns.get_loc("Low")] = 87.0
    r, _ = main.swing_exitinval_exit_reason(nxt, entry_day, 100.0, 2.0, 100.0)
    assert r == "stop_hit"
    # no hit when low stays above stop
    ok = _bars([100.0] * 41)
    r, _ = main.swing_exitinval_exit_reason(ok, entry_day, 100.0, 2.0, 100.0)
    assert r is None
    # gap-down open below the stop
    gap = _bars([100.0] * 41)
    gap.iloc[-1, gap.columns.get_loc("Open")] = 80.0
    r, _ = main.swing_exitinval_exit_reason(gap, entry_day, 100.0, 2.0, 100.0)
    assert r == "stop_hit"


def _weekly_series(n_weeks, turn_after_week=None, per_week=5):
    """Rising weekly closes, then falling from turn_after_week."""
    out = []
    lvl = 100.0
    for w in range(n_weeks):
        lvl += 2.0 if (turn_after_week is None or w < turn_after_week) else -6.0
        out += [lvl] * per_week
    return out


def test_weekly_flags_match_research_reference():
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "efr", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "exit_family_research.py"))
    efr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(efr)
    df = _bars(_weekly_series(45, turn_after_week=35))
    ref, _ = efr._weekly_down_flags(df.index, df["Close"].to_numpy())
    mine = main.weekly_ema13_down_flags(df["Date"], df["Close"].to_numpy())
    assert (ref == mine).all()
    assert mine.any() and not mine[:100].any()


def test_weekly_turn_exit_fires_only_on_onset_and_no_lookahead():
    df = _bars(_weekly_series(45, turn_after_week=35))
    flags = main.weekly_ema13_down_flags(df["Date"], df["Close"].to_numpy())
    onset = int(np.argmax(flags))
    assert onset > 0
    entry_idx = onset - 3
    entry_day = df["Date"].iloc[entry_idx]
    big_atr = 1e-6  # stop effectively at entry price; make entry so low the stop is never hit
    # stop far below: entry_price 1e-3 -> stop negative, never hit
    r, _ = main.swing_exitinval_exit_reason(df.iloc[:onset], entry_day, 1.0, 0.1, 100.0)
    assert r is None                       # before the onset bar: nothing
    r, _ = main.swing_exitinval_exit_reason(df.iloc[:onset + 1], entry_day, 1.0, 0.1, 100.0)
    assert r == "signal_invalidation"
    # onset day is the first day of a new week: the turn relies on the PREVIOUS completed week only,
    # so truncating inside the week that created the down-turn must not trigger earlier
    first_down_week_start = onset - (onset % 5) if False else onset
    r, _ = main.swing_exitinval_exit_reason(df.iloc[:onset - 1], entry_day, 1.0, 0.1, 100.0)
    assert r is None


def test_incomplete_week_does_not_trigger():
    # weekly trend rising; last (partial) week crashes. Flags use completed weeks only -> no exit.
    closes = _weekly_series(40) + [50.0, 50.0]   # partial week of 2 crash days
    df = _bars(closes)
    entry_day = df["Date"].iloc[-6]
    r, _ = main.swing_exitinval_exit_reason(df, entry_day, 1.0, 0.1, 100.0)
    assert r is None


def test_thirty_day_timeout_and_running_max():
    df = _bars([100.0] * 80)           # flat: no stop, no weekly turn
    entry_day = df["Date"].iloc[39]
    r, rm = main.swing_exitinval_exit_reason(df.iloc[:69], entry_day, 100.0, 2.0, 100.0)
    assert r is None                   # 29 bars held
    r, rm = main.swing_exitinval_exit_reason(df.iloc[:70], entry_day, 100.0, 2.0, 100.0)
    assert r == "max_hold_timeout"     # 30 bars held
    assert rm == 100.0


def test_adapter_recovers_entry_from_frozen_stop():
    df = _bars([100.0] * 41)
    entry_day = df["Date"].iloc[39]
    stop = main.swing_exitinval_stop(100.0, 2.0)
    df.iloc[-1, df.columns.get_loc("Low")] = stop - 0.01
    r, _ = main._swing_exitinval_adapter(df, entry_day, stop, 2.0, 100.0)
    assert r == "stop_hit"
    df.iloc[-1, df.columns.get_loc("Low")] = stop + 0.5
    r, _ = main._swing_exitinval_adapter(df, entry_day, stop, 2.0, 100.0)
    assert r is None


def test_scan_chain_uses_new_tags_and_6atr_stop():
    import inspect
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "SWING_EXITINVAL_VP_TAG, volume_profile_poc_entry_signal" in src
    assert "SWING_EXITINVAL_OB_TAG, order_block_entry_signal" in src
    assert "swing_exitinval_stop(entry_price, _sig[\"atr_at_entry\"])" in src
    assert "swing_obvp_exit_fn(pos[\"strategy\"])" in src
