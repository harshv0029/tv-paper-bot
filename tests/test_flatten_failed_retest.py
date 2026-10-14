"""B-1120 flatten failed-cell re-test planner + B-1030/B-1031 avg-hold unit consistency."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import flatten_failed_retest as ff  # noqa: E402
import intraday_flatten_rerun as fr  # noqa: E402
import strategy_registry as sr  # noqa: E402

T = "chan_kalman__band_mr__short__5m__atr4d0_hold40_ve10d0e4_z2d0__v1"


def _d(name, pf):
    return sr.StrategyDef(name=name, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(sr.TradeCategory.BUY,), timeframe="5m",
                          status=sr.StrategyStatus.RESEARCH, metrics=sr.Metrics(pfnet=pf, pfgross=pf, win_rate_pct=50, n_trades=100))


def test_default_cost_tag_unchanged_and_cost_tag_matches_precedent():
    assert fr.flat_tag(T) == T[:-4] + "_fl1515__v2"
    assert fr.flat_tag(T, 0.8) == fr.flat_tag(T)
    assert fr.flat_tag(T, 0.3) == "chan_kalman__band_mr__short__5m__atr4d0_cst0d3_hold40_ve10d0e4_z2d0_fl1515__v2"
    assert fr.flat_tag(T, 0.12) != fr.flat_tag(T, 0.3)


def test_source_tag_round_trips_with_cost_param():
    assert fr.source_tag(fr.flat_tag(T, 0.3)) == T
    assert fr.source_tag(fr.flat_tag(T)) == T


def test_cost_param_alphabetical_for_pattern_tags():
    t = "lunar__full_new__short__15m__atr6_h25__v1"
    assert fr.flat_tag(t, 0.3) == "lunar__full_new__short__15m__atr6_cst0d3_h25_fl1515__v2"
    t2 = "lunar__full_new__short__15m__atrnone_h25__v1"
    assert fr.flat_tag(t2, 0.3).split("__")[4] == "atrnone_cst0d3_h25_fl1515"


def test_failed_cells_derived_from_floor_not_baked_in():
    reg = [_d(fr.flat_tag(T), 0.9), _d(fr.flat_tag(T.replace("z2d0", "z1d0")), 1.5), _d(fr.flat_tag(T, 0.3), 0.5), _d(T, 0.4)]
    names = [d.name for d in ff.failed_cells(reg, 1.1)]
    assert names == [fr.flat_tag(T)]  # passed cell, already-retested cst tag and non-flatten tag are not "failed"
    assert [d.name for d in ff.failed_cells(reg, 0.5)] == []  # a changed floor re-decides without re-running anything


def test_plan_skips_existing_retests_and_handles_universe_suffix():
    base = fr.flat_tag(T)
    lun = fr.flat_tag("lunar__full_new__short__15m__atr6_h25__v1") + "|n200"
    reg = [_d(base, 0.9), _d(fr.flat_tag(T, 0.3), 0.7), _d(lun, 0.8)]
    p = ff.plan(reg, 1.1)
    g = {(x["family"], x["interval"]): x for x in p["groups"]}
    assert g[("chan_kalman", "5m")]["retests_done"] == 1 and g[("chan_kalman", "5m")]["retests_new"] == 1
    assert ("pattern_n200", "15m") in g
    assert ff.retest_tag(lun, 0.3) == "lunar__full_new__short__15m__atr6_cst0d3_h25_fl1515__v2|n200"
    assert p["owed"]


def test_real_registry_plan_is_consistent():
    p = ff.plan()
    assert p["failed_total"] == sum(g["failed"] for g in p["groups"]) + len(p["unmapped"])
    assert all(c["cost"] in ff.COSTS for c in ff.matrix()["include"])
    # every failed cell is below the live floor and none carries a cost param
    assert all(d.metrics.pfnet < sr.PFNET_LIVE_FLOOR and "_cst" not in d.name for d in ff.failed_cells())


def test_avg_held_hrs_matches_raw_bars_times_market_hours_per_bar():
    """B-1030: where the raw bar count is stored, hours must be bars x market hours of the tag's timeframe (108 15m tags were bars-as-hours)."""
    bad = []
    for s in sr.REGISTRY:
        m = s.metrics
        if m is None or not m.avg_held_bars or m.avg_held_hrs is None:
            continue
        exp = m.avg_held_bars * sr.market_hours_per_bar(s.timeframe)
        if abs(m.avg_held_hrs - exp) > 0.01 * max(exp, 1.0):
            bad.append((s.name, s.timeframe, m.avg_held_bars, m.avg_held_hrs))
    assert not bad, bad[:5]
