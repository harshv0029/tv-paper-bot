"""Tests for /strategy-info (2026-09-30, explicit user instruction: "I
want to get those dashed cells filled too... which strategy and what are
details of that strategy... Work on it. Why it was not filled. No
excuses"). Unlike /strategy-leaderboard (top-N-per-category only), this
returns EVERY registered strategy so a live trade's own strategy is
never "missing" just because it's outside its category's current top 5
- see strategy_registry.all_strategies_info()'s own docstring for why
that distinction matters (range_short_staged_ladder is the real wired
RANGE-regime short exit but doesn't rank in short_sell's top 5)."""
import strategy_registry as sr
import main


def test_returns_one_entry_per_registered_strategy():
    result = main.strategy_info()
    assert set(result.keys()) == {s.name for s in sr.REGISTRY}


def test_matches_the_real_registry_all_strategies_info():
    assert main.strategy_info() == sr.all_strategies_info()


def test_a_strategy_outside_its_categorys_top_n_still_has_real_metrics():
    # range_short_staged_ladder (PFnet 0.21) does not rank in short_sell's
    # current top 5 (see test_strategy_leaderboard_endpoint.py's own top5
    # list) - it must still show up here with its real numbers, not be
    # silently dropped the way /strategy-leaderboard alone would.
    result = main.strategy_info()
    row = result["range_short_staged_ladder"]
    assert row["pfnet"] == 0.21
    assert row["win_rate_pct"] == 44.9
    assert row["category"] is None
    assert row["rank"] is None
    assert row["categories"] == ["short_sell"]


def test_a_top_ranked_strategy_reports_its_category_and_rank():
    result = main.strategy_info()
    row = result["universal_score"]
    assert row["category"] == "buy"
    assert row["rank"] == 3


def test_every_row_carries_viable_and_never_fabricates_metrics_for_unvalidated_strategies():
    result = main.strategy_info()
    for name, row in result.items():
        s = next(s for s in sr.REGISTRY if s.name == name)
        assert row["viable"] == s.is_viable()
        if s.metrics is None:
            assert row["pfnet"] is None and row["win_rate_pct"] is None
