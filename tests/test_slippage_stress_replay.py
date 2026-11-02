"""B-422: cost override on the main module, turnover filter helper and stressed-tag naming."""
import os
import sys
import types

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import slippage_stress_replay as ss  # noqa: E402


def _frame(n=30, close=100.0, vol=200_000.0):
    return pd.DataFrame({"Date": pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
                         "Open": close, "High": close, "Low": close, "Close": [close] * n, "Volume": [vol] * n})


def test_cost_override_sets_and_restores_main_module():
    import main as m
    orig = m.ROUND_TRIP_COST_PCT
    prev = ss.apply_cost_override(m, 1.6)
    try:
        assert prev == orig
        assert m.ROUND_TRIP_COST_PCT == 1.6
        # real main.py readers see the stressed value through the proxy too
        assert ss.FilteredMain(m, 0).ROUND_TRIP_COST_PCT == 1.6
    finally:
        ss.apply_cost_override(m, prev)
    assert m.ROUND_TRIP_COST_PCT == orig


def test_avg_turnover_cr_uses_last_20_bars_inclusive():
    df = _frame()  # 100 x 200k = 2 Cr per bar
    assert abs(ss.avg_turnover_cr(df) - 2.0) < 1e-9
    df.loc[len(df) - 1, "Volume"] = 2_200_000.0  # signal bar: 22 Cr -> mean (19*2 + 22)/20 = 3
    assert abs(ss.avg_turnover_cr(df) - 3.0) < 1e-9
    assert np.isnan(ss.avg_turnover_cr(_frame(n=19)))
    assert np.isnan(ss.avg_turnover_cr(_frame().drop(columns=["Volume"])))


def test_turnover_ok_thresholds():
    df = _frame()  # 2 Cr
    assert ss.turnover_ok(df, 0)
    assert ss.turnover_ok(df, 1)
    assert ss.turnover_ok(df, 2)
    assert not ss.turnover_ok(df, 5)
    assert not ss.turnover_ok(_frame(n=10), 1)  # unknown turnover fails any positive threshold
    assert ss.turnover_ok(_frame(n=10), 0)


def test_filtered_main_drops_and_counts_only_illiquid_signals():
    calls = []

    def entry(win, *a):
        calls.append(len(win))
        return {"entry_price": 1.0, "stop_loss": 0.9}

    fake = types.SimpleNamespace(gap_and_go_entry_signal=entry, ROUND_TRIP_COST_PCT=0.8)
    p5 = ss.FilteredMain(fake, 5)
    assert p5.gap_and_go_entry_signal(_frame()) is None  # 2 Cr < 5 Cr
    assert p5.dropped == 1
    assert ss.FilteredMain(fake, 1).gap_and_go_entry_signal(_frame()) is not None
    assert ss.FilteredMain(fake, 0).gap_and_go_entry_signal(_frame(n=5)) is not None
    assert p5.ROUND_TRIP_COST_PCT == 0.8  # non-entry attributes pass through
    assert len(calls) == 3  # the real fn is always called first


def test_stress_tag_naming_grammar():
    assert ss.fmt_num(1.2) == "1d2" and ss.fmt_num(0.8) == "0d8" and ss.fmt_num(5) == "5" and ss.fmt_num(0.5) == "0d5"
    assert (ss.stress_tag("gap_and_go__exitinval__long__1d__atr6d0_hold30_sigelder__v2", 1.2, 5)
            == "gap_and_go__exitinval__long__1d__atr6d0_cost1d2_hold30_sigelder_turncr5__v2")
    assert ss.stress_tag("primary_base", 1.6, 0) == "primary_base__cost1d6_turncr0"
    tags = {ss.stress_tag("primary_base", c, t) for c in (0.8, 1.2, 1.6) for t in (0, 1, 5)}
    assert len(tags) == 9  # every cell its own tag


def test_select_tags_viable_replayable_sorted():
    def s(name, pf, viable=True, hold=5.0):
        return types.SimpleNamespace(name=name, is_viable=lambda: viable,
                                     metrics=types.SimpleNamespace(pfnet=pf, avg_held_bars=hold))
    reg = [s("primary_base", 2.0), s("power_play_high_tight_flag", 5.0), s("gap_and_go_swing", 9.0, viable=False),
           s("not_replayable", 99.0), s("minervini_vcp__swing__long__1d__benone__v1", 2.0, hold=1.0)]
    assert ss.select_tags(reg, 2) == ["power_play_high_tight_flag", "minervini_vcp__swing__long__1d__benone__v1"]


def test_plan_matrix_from_real_registry():
    p = ss.plan({"NSHARDS": "2", "TOP_N": "10"})
    tags = {x["tag"] for x in p["include"]}
    assert 1 <= len(tags) <= 10 and all(t in ss.REPLAYABLE for t in tags)
    assert len(p["include"]) == 2 * len(tags)
