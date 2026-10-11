"""brk20_min_rr (B-798): unit tests for the main.py ports + parity with the research simulator
(scripts/douglas_trade_mgmt_research.py sim_r) + the replay driver's exact-mergeable aggregation.
Synthetic data only; the full-universe replay is brk20-min-rr-main-replay.yml."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brk20_replay as R  # noqa: E402


def _frame(close, open_=None, high=None, low=None):
    close = np.asarray(close, float)
    open_ = close.copy() if open_ is None else np.asarray(open_, float)
    high = np.maximum(close, open_) + 0.3 if high is None else np.asarray(high, float)
    low = np.minimum(close, open_) - 0.3 if low is None else np.asarray(low, float)
    d = pd.date_range("2024-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"Date": d, "Open": open_, "High": high, "Low": low, "Close": close,
                         "Volume": np.full(len(close), 1000.0)})


def _breakout_long(n=100, last=108.0):
    close = np.full(n, 100.0)
    close[-1] = last
    return _frame(close)


def _breakdown_short(n=100, last=92.0):
    close = np.full(n, 100.0)
    close[-1] = last
    return _frame(close)


def test_long_entry_has_atr_stop_and_room():
    df = _breakout_long()
    # room to prior 60-bar high (100.3) is NEGATIVE after a jump to 108 -> any min_rr > 0 rejects
    assert main.brk20_min_rr_entry_signal(df, "long", 3.0, 1.0) is None
    # ... but with the 60-bar high far above, room is positive
    h = df["High"].to_numpy().copy()
    h[40] = 140.0
    df2 = df.assign(High=h)
    sig = main.brk20_min_rr_entry_signal(df2, "long", 3.0, 4.0)
    assert sig is not None
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 3.0 * sig["atr_at_entry"])
    assert sig["room"] >= 4.0 * sig["risk"] - 1e-9
    assert sig["room_target"] == 140.0


def test_min_rr_filter_blocks_when_room_small():
    df = _breakout_long()
    h = df["High"].to_numpy().copy()
    h[:60] = 112.0
    df2 = df.assign(High=h)
    s_lo = main.brk20_min_rr_entry_signal(df2, "long", 1.0, 0.5)
    assert s_lo is not None
    s_hi = main.brk20_min_rr_entry_signal(df2, "long", 1.0, 50.0)
    assert s_hi is None


def test_short_is_mirror_and_stop_above_entry():
    df = _breakdown_short()
    low = df["Low"].to_numpy().copy()
    low[40] = 60.0
    df2 = df.assign(Low=low)
    sig = main.brk20_min_rr_entry_signal(df2, "short", 3.0, 4.0)
    assert sig is not None
    assert sig["stop_loss"] > sig["entry_price"]
    assert sig["room_target"] == 60.0
    assert main.brk20_min_rr_entry_signal(df2, "long", 3.0, 0.0) is None


def test_no_breakout_no_signal_and_short_history():
    df = _frame(np.full(100, 100.0))
    assert main.brk20_min_rr_entry_signal(df, "long", 3.0, 0.0) is None
    assert main.brk20_min_rr_entry_signal(df.iloc[:40], "long", 3.0, 0.0) is None
    assert main.brk20_min_rr_entry_signal(df, "sideways") is None


def test_stop_price_helper_never_missing():
    assert main.brk20_stop_price(100, 2, 3, "long") == 94
    assert main.brk20_stop_price(100, 2, 3, "short") == 106


def _pos_frame(highs, lows, closes, opens=None):
    n = len(closes)
    return _frame(closes, open_=opens, high=highs, low=lows).iloc[:n]


def test_exit_stop_loss_gap_aware_long():
    # fill bar 0 (entry 100, stop 94), bar 1 gaps open at 90 -> fills at the open, not the stop
    df = _pos_frame([101, 91], [99, 89], [100, 90], opens=[100, 90])
    r, px = main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 94.0, "long")
    assert (r, px) == ("stop_loss", 90.0)


def test_exit_stop_on_fill_bar_fills_at_stop():
    df = _pos_frame([101], [93], [95], opens=[100])
    assert main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 94.0, "long") == ("stop_loss", 94.0)


def test_exit_short_stop_gap_aware():
    df = _pos_frame([101, 111], [99, 109], [100, 110], opens=[100, 110])
    r, px = main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 106.0, "short")
    assert (r, px) == ("stop_loss", 110.0)


def test_breakeven_ratchet_protected_stop():
    # R = 6 (entry 100, stop 94). Bar0 high 107 (>= 1R). Bar1 trades back to 100.2 low -> BE stop 100.3 hit
    df = _pos_frame([107, 112], [99, 100.0], [106, 110], opens=[100, 104])
    assert main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 94.0, "long", None)[0] is None
    r, px = main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 94.0, "long", 1.0)
    assert r == "protected_stop"
    assert px == pytest.approx(100.3)


def test_rule_exit_needs_ema_down_and_not_fill_bar():
    closes = list(np.linspace(100, 120, 40)) + list(np.linspace(120, 100, 10))
    df = _frame(closes)
    day = df["Date"].iloc[39]
    r, px = main.brk20_min_rr_exit_reason(df, day, closes[39], 1.0, "long")
    assert r == "rule_exit" and px == closes[-1]
    # on the fill bar itself a rule exit is never taken
    assert main.brk20_min_rr_exit_reason(df, df["Date"].iloc[-1], closes[-1], 1.0, "long")[0] is None


def test_max_hold_timeout():
    closes = np.full(40, 100.0)
    df = _frame(closes)
    day = df["Date"].iloc[5]
    j_last = 5 + main.BRK20_MAX_HOLD_BARS
    assert main.brk20_min_rr_exit_reason(df.iloc[:j_last], day, 100.0, 50.0, "long")[0] is None
    r, px = main.brk20_min_rr_exit_reason(_frame(np.full(j_last + 1, 100.0)), day, 100.0, 50.0, "long")
    assert r == "max_hold_timeout" and px == 100.0


def test_never_returns_without_stop_semantics_bad_inputs():
    df = _frame(np.full(10, 100.0))
    assert main.brk20_min_rr_exit_reason(df, "2099-01-01", 100.0, 90.0) == (None, None)
    assert main.brk20_min_rr_exit_reason(df, df["Date"].iloc[0], 100.0, 100.0) == (None, None)
    assert main.brk20_min_rr_exit_reason(df.iloc[:0], "x", 1, 1) == (None, None)


# ---------------------------------------------------------------- parity with the research simulator
@pytest.mark.parametrize("direction", ["long", "short"])
@pytest.mark.parametrize("be", [None, 1.0])
def test_parity_with_research_sim(direction, be):
    import douglas_trade_mgmt_research as dr
    am, rr = 2.0, 1.0
    opt = {"min_rr": rr}
    if be is not None:
        opt["be_r"] = be
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    total = 0
    for seed in range(6):
        df = R.synthetic_frame(seed, n=700)
        sig = dr.b_brk(df)
        want = dr.sim_r(df, sig, direction, am, opt)
        got = R.replay_symbol(main, df, direction, am, rr, be, cost)
        # research drops a trade still open at data end differently (reason data_end) - compare closed trades
        want_c = [t for t in want if t["reason"] != "data_end"]
        got_c = [t for t in got if t["reason"] != "data_end_forced_close"]
        assert len(got_c) == len(want_c), (seed, len(got_c), len(want_c))
        for a, b in zip(got_c, want_c):
            assert a["net"] == pytest.approx(b["ret"], abs=1e-9)
            assert a["held"] == b["hold"]
        total += len(want_c)
    assert total > 0


# ---------------------------------------------------------------- replay aggregation
def test_tags_follow_grammar():
    assert R.make_tag("short", "1d", 3, 4) == "brk20_min_rr__main_replay__short__1d__atr3_rr4__v1"
    assert R.make_tag("long", "1h", 3.0, 3.5, 1.0) == "brk20_min_rr__main_replay__long__1h__atr3_be1_rr3d5__v1"


def test_aggregation_merge_is_exact():
    ts = [{"gross": 0.05, "net": 0.042, "held": 4, "reason": "rule_exit"},
          {"gross": -0.03, "net": -0.038, "held": 2, "reason": "stop_loss"},
          {"gross": 0.1, "net": 0.092, "held": 9, "reason": "rule_exit"}]
    whole = R.agg_new()
    R.agg_add(whole, ts)
    a, b = R.agg_new(), R.agg_new()
    R.agg_add(a, ts[:1])
    R.agg_add(b, ts[1:])
    R.agg_merge(a, b)
    assert R.agg_metrics(a) == R.agg_metrics(whole)
    m = R.agg_metrics(whole)
    assert m["n"] == 3 and m["win_pct"] == pytest.approx(66.67)
    assert m["pfnet"] == pytest.approx((0.042 + 0.092) / 0.038)
    assert m["exit_reasons"]["stop_loss"]["n"] == 1


def test_plan_matrix_default_and_cap():
    import brk20_plan as P
    m = P.build({})
    assert len(m["include"]) == 3 * 2 * 6
    import json
    cells = json.loads(m["include"][0]["cells"])
    assert len(cells) == 2 * 3 * 2 and {"atr": 3.0, "rr": 4.0, "be": None} in cells
    assert {"atr": 3.0, "rr": 3.0, "be": 1.0} in cells
    with pytest.raises(SystemExit):
        P.build({"NSHARDS": "30"})
