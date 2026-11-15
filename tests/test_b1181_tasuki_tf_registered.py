"""B-1181: tasuki sweep run 43701581391 registers 60 distinct `_tfs` tags; only etf short 1d passes and it is already live."""
import main
import strategy_registry as sr


def test_rows_registered_and_only_live_cells_pass():
    rows = [s for s in sr.REGISTRY if "_tfs__" in s.name and s.name.startswith("tasuki__")]
    assert len(rows) == 60 and len({s.name for s in rows}) == 60
    passing = {s.name for s in rows if s.metrics.pfnet > 1.0}
    assert passing and all("__gap_etf_tfs__short__1d__" in n for n in passing)
    for n in passing:
        assert n.replace("_tfs", "") in main.TASUKI_SHORT_CELLS
