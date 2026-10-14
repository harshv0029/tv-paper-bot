"""B-1232: every grammar tag in the saved backtest JSONs is in the registry or explicitly explained; the new loader keeps raw fields."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import missing_registry_tags as mr  # noqa: E402
import strategy_registry as sr  # noqa: E402
import strategy_registry_b1232 as b  # noqa: E402


def test_no_unexplained_missing_tags():
    names = {s.name for s in sr.REGISTRY}
    per_file, skipped = mr.scan(os.path.join(ROOT, "docs", "backtest_data"), names)
    missing = sorted({t for v in per_file.values() for t in v["missing"]})
    assert not skipped and not missing, missing[:10]


def test_loader_rows_are_unique_and_research_only():
    mine = {s.source for s in sr.REGISTRY}  # noqa: F841
    new = {x.name for x in b.build()}  # build() skips names already registered, so it is empty once loaded
    assert not new
    reg = [s for s in sr.REGISTRY if "B-1232" in s.notes]
    names = [s.name for s in sr.REGISTRY]
    assert len(names) == len(set(names))
    assert len(reg) >= 366
    for s in reg:
        assert s.entry_fn is None and s.metrics is not None


def test_thin_and_undefined_rows_keep_their_real_n_and_fail_closed():
    by = {s.name: s for s in sr.REGISTRY}
    t = by["swingminrr__minervini_vcp_gate__long__1d__atr2_rr4__v1"]
    assert t.metrics.n_trades == 23 and t.metrics.avg_held_bars == 13.0
    u = by["breadth__nhnl_turn__long__1d__atr2__v1"]
    assert u.metrics.pfnet == 0.0 and "UNDEFINED" in u.evidence


def test_sizing_rows_are_the_only_explained_exclusion():
    assert set(mr.EXPLAINED_PREFIX) == {"sizing__"}
