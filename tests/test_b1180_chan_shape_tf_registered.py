"""B-1180: chan_shape candle/dir sweep run 43696407370 registers all 60 cells as distinct `_tfs` tags; all fail, none wired."""
import main
import strategy_registry as sr


def test_all_cells_registered_failing_and_unwired():
    rows = [s for s in sr.REGISTRY if s.name.startswith("chan_shape__mom_mr_tfs__")]
    assert len(rows) == 60 and len({s.name for s in rows}) == 60
    assert all(s.metrics.pfnet <= 1.0 for s in rows)
    assert {s.name.split("__")[2] for s in rows} == {"long", "short"}
    assert {s.name.split("__")[3] for s in rows} == {"1d", "4h", "1h", "15m", "5m"}
    assert not any(s.name in main._replay_verified_tags() for s in rows)
