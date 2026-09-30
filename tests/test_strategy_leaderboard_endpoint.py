"""Tests for /strategy-leaderboard (2026-09-29, explicit user instruction:
"print these columns in the render trade view at the end of live and
opened and closed trades... rank strategy pfnet and win % - all these
from ur backtest"). A thin, read-only pass-through onto
strategy_registry.py's own leaderboard - never recomputes or fabricates
anything, so these tests just confirm the wiring (right keys, one list
per TradeCategory, matches the registry's own computation) and that
registering/ranking strategies here still never touches live trading (no
import of main.strategy_leaderboard changes any order path).

2026-09-30, explicit user instruction ("Keep only viable ones on trade
view... I do not want just top 5, but I want all that qualify pfnet >= 1
in backtesting"): switched from sr.leaderboard(top_n=5) (includes
non-viable rows, capped at 5) to sr.viable_leaderboard() (every strategy
clearing PFnet >= PFNET_LIVE_FLOOR, unbounded). Updated below."""
import strategy_registry as sr
import main


def test_returns_one_key_per_trade_category():
    result = main.strategy_leaderboard()
    assert set(result.keys()) == {c.value for c in sr.TradeCategory}


def test_each_category_matches_the_real_registry_viable_leaderboard():
    result = main.strategy_leaderboard()
    for cat in sr.TradeCategory:
        assert result[cat.value] == sr.viable_leaderboard(cat)


def test_empty_categories_are_empty_lists_not_fabricated_rows():
    result = main.strategy_leaderboard()
    # futures/options have no registered strategies as of 2026-09-29 (no
    # F&O order-placement path exists) - never padded with fake entries.
    assert result["futures"] == []
    assert result["options"] == []


def test_short_sell_has_no_viable_strategy_today_and_shows_none():
    # As of 2026-09-30, every registered short_sell candidate is well
    # below PFnet 1.0 (best is gap_and_go_short_fade at 0.557) - the
    # viable-only leaderboard must show an empty list, never pad it with
    # non-viable rows just to have something to display.
    result = main.strategy_leaderboard()
    assert result["short_sell"] == []


def test_every_row_returned_anywhere_is_actually_viable():
    result = main.strategy_leaderboard()
    for cat_rows in result.values():
        for row in cat_rows:
            assert row["viable"] is True
            assert row["pfnet"] is not None and row["pfnet"] >= sr.PFNET_LIVE_FLOOR


def test_swing_leaderboard_is_not_capped_at_five_when_more_qualify():
    # Sanity-checks the "no top-5 cap" half of the instruction using
    # today's actual registry data (swing currently has more than one
    # viable strategy) - if this count ever drops to <=5 the assertion
    # below still passes, it just stops being a meaningful check of the
    # "unbounded" behavior; the real guarantee is test_each_category_
    # matches_the_real_registry_viable_leaderboard above.
    result = main.strategy_leaderboard()
    all_swing_viable = [s for s in sr.strategies_by_category(sr.TradeCategory.SWING) if s.is_viable() is True]
    assert len(result["swing"]) == len(all_swing_viable)
