"""B-1480: Elder batch-3 main.py replay run 41966382565 - all rows registered research-only, none wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data",
                   "elder_b3_main_replay_41966382565.json")


def test_all_rows_registered_with_real_metrics():
    rows = json.load(open(_FN))["rows"]
    assert len(rows) == 30
    by = {s.name: s for s in sr.REGISTRY}
    for r in rows:
        s = by[r["tag"]]
        assert s.entry_fn is None and s.status == sr.StrategyStatus.RESEARCH
        assert s.metrics.n_trades == r["n"] and s.metrics.pfnet == r["pfnet"]
        assert "41966382565" in s.metrics.run_ref
        assert not s.is_viable()  # best row 0.961: nothing clears the floor
