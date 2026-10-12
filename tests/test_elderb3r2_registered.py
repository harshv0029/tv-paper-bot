"""Run 38211452647 (Elder batch 3, NIFTY200+ETF universe): raw data kept intact, all 492 tags registered research-only, never live-wired."""
import json
import os

import strategy_registry as sr
import strategy_registry_elderb3r2 as m

_D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data")


def _rows():
    return json.load(open(os.path.join(_D, "elder_batch3_n200etf_38211452647_results.json")))["rows"]


def test_raw_kept_and_all_tags_registered_research_only():
    rows = _rows()
    assert len(rows) == 492
    assert os.path.exists(os.path.join(_D, "elder_batch3_n200etf_38211452647_table.txt"))
    by = {s.name: s for s in sr.REGISTRY}
    for r in rows:
        s = by[m.tag_for(r["tag"])]
        assert s.entry_fn is None and s.status == sr.StrategyStatus.RESEARCH
        assert s.metrics.n_trades == r["n"]
        assert abs(s.metrics.win_rate_pct - r["win_pct"]) < 1e-9
        assert "38211452647" in s.metrics.run_ref and "NOT" in s.metrics.universe
        if r["pfnet"] is None:
            assert s.metrics.pfnet == 0.0 and not s.is_viable()
        else:
            assert s.metrics.pfnet == r["pfnet"]


def test_old_full_universe_tags_untouched_and_new_names_distinct():
    by = {s.name: s for s in sr.REGISTRY}
    old = by["osc__div_class__long__1d__atr3_kb_oscrsi__v1"]
    assert "38169625565" in old.metrics.run_ref
    new = by["osc__div_class__long__1d__atr3_kb_oscrsi_rn38211452647__v1"]
    assert new.metrics.pfnet == 2.433 and new.metrics.n_trades == 10676


def test_builder_never_duplicates():
    assert m.build() == []
    assert len({s.name for s in sr.REGISTRY}) == len(sr.REGISTRY)
