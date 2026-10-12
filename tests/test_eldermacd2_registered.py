"""Run 38208431466 (Elder MACD/directional/gap re-run): raw data kept intact, every tag present in the registry, never overwritten."""
import json
import os

import strategy_registry as sr

_D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data")


def test_rerun_raw_kept_and_all_tags_registered():
    rows = json.load(open(os.path.join(_D, "elder_macd_dirgap_38208431466_results.json")))["rows"]
    assert len(rows) == 120
    assert os.path.exists(os.path.join(_D, "elder_macd_dirgap_38208431466_table.txt"))
    names = {s.name for s in sr.REGISTRY}
    assert all(r["tag"] in names for r in rows)


def test_rerun_builder_never_duplicates():
    import strategy_registry_eldermacd2 as dr
    assert dr.build() == []
    assert len({s.name for s in sr.REGISTRY}) == len(sr.REGISTRY)
