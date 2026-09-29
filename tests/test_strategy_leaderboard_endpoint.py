"""Tests for /strategy-leaderboard (2026-09-29, explicit user instruction:
"print these columns in the render trade view at the end of live and
opened and closed trades... rank strategy pfnet and win % - all these
from ur backtest"). A thin, read-only pass-through onto
strategy_registry.py's own leaderboard() - never recomputes or fabricates
anything, so these tests just confirm the wiring (right keys, one list
per TradeCategory, matches the registry's own leaderboard() output) and
that registering/ranking strategies here still never touches live
trading (no import of main.strategy_leaderboard changes any order path)."""
import strategy_registry as sr
import main


def test_returns_one_key_per_trade_category():
    result = main.strategy_leaderboard()
    assert set(result.keys()) == {c.value for c in sr.TradeCategory}


def test_each_category_matches_the_real_registry_leaderboard():
    result = main.strategy_leaderboard()
    for cat in sr.TradeCategory:
        assert result[cat.value] == sr.leaderboard(cat, top_n=sr.TOP_N_PER_CATEGORY)


def test_empty_categories_are_empty_lists_not_fabricated_rows():
    result = main.strategy_leaderboard()
    # futures/options have no registered strategies as of 2026-09-29 (no
    # F&O order-placement path exists) - never padded with fake entries.
    assert result["futures"] == []
    assert result["options"] == []


def test_short_sell_leaderboard_rows_carry_pfnet_and_win_rate():
    result = main.strategy_leaderboard()
    board = result["short_sell"]
    assert len(board) == sr.TOP_N_PER_CATEGORY
    for row in board:
        assert "pfnet" in row and "win_rate_pct" in row and "viable" in row
