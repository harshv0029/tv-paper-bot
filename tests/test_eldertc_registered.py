"""Run 38209280422 (Elder trend-context): raw data kept intact, all 210 tags registered research-only with real metrics."""
import json
import os

import strategy_registry as sr

_D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data")


def _rows():
    return json.load(open(os.path.join(_D, "elder_trend_context_38209280422_results.json")))["rows"]


def test_raw_kept_and_all_tags_registered():
    rows = _rows()
    assert len(rows) == 210
    assert os.path.exists(os.path.join(_D, "elder_trend_context_38209280422_table.txt"))
    by = {s.name: s for s in sr.REGISTRY}
    for r in rows:
        s = by[r["tag"]]
        assert s.entry_fn is None
        assert s.metrics.pfnet == r["pfnet"] and s.metrics.n_trades == r["n"]
        assert abs(s.metrics.win_rate_pct - r["win_pct"]) < 1e-9
        assert "38209280422" in s.metrics.run_ref


def test_none_viable_and_directions():
    rows = _rows()
    assert max(r["pfnet"] for r in rows) < sr.PFNET_LIVE_FLOOR
    by = {s.name: s for s in sr.REGISTRY}
    assert any("__short__" in r["tag"] for r in rows)
    for r in rows:
        want = sr.TradeCategory.SHORT_SELL if "__short__" in r["tag"] else sr.TradeCategory.SWING
        assert by[r["tag"]].categories == (want,)


def test_builder_never_duplicates():
    import strategy_registry_eldertc as m
    assert m.build() == []
    assert len({s.name for s in sr.REGISTRY}) == len(sr.REGISTRY)
