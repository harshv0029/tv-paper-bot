"""2026-10-07 thumb rule: PFnet > 1 and hold <= 30d => viable, hold time never vetoes."""
import strategy_registry as sr


def test_long_hold_strategy_with_pfnet_above_floor_is_viable():
    s = next(x for x in sr.REGISTRY if x.name == "gap_and_go__swing__long__1d__hold60__v1")
    assert s.metrics.avg_held_hrs and s.metrics.avg_held_hrs > 28 * 6
    assert s.is_viable() is True
    assert s.name in {r["name"] for c in s.categories for r in sr.viable_leaderboard(c)}
