"""Tests for the strategy registry + leaderboard (2026-09-28, extended
2026-09-29 - see strategy_registry.py's own module docstring). This
module is not wired into main.py's live path; these tests only cover
the scaffold's own bookkeeping/ranking logic."""
import strategy_registry as sr


def test_registry_names_are_unique():
    names = [s.name for s in sr.REGISTRY]
    assert len(names) == len(set(names))


def test_live_strategies_match_known_live_engines():
    # 2026-09-28: fixed after discovering gap_and_go_swing is ALSO live
    # (both paper and real) on SWING_WATCHLIST - this registry's first
    # version incorrectly listed universal_score as the only live one.
    live_names = {s.name for s in sr.strategies_by_status(sr.StrategyStatus.LIVE)}
    assert live_names == {"universal_score", "gap_and_go_swing"}


def test_every_strategy_has_evidence_pointer():
    for strat in sr.REGISTRY:
        assert strat.evidence, f"{strat.name} has no evidence pointer for its status"


def test_strategies_by_asset_class_filters_correctly():
    swing = sr.strategies_by_asset_class(sr.AssetClass.EQUITY_SWING)
    assert all(s.asset_class == sr.AssetClass.EQUITY_SWING for s in swing)
    assert "minervini_trend_template_vcp" in [s.name for s in swing]


def test_scan_universe_skips_strategies_without_entry_fn():
    # Every registered strategy today has entry_fn=None (none are wired
    # in yet) - scan_universe must skip them rather than raise.
    calls = []

    def fake_data(symbol):
        calls.append(symbol)
        return {"symbol": symbol}

    signals = sr.scan_universe(["FOO.NS", "BAR.NS"], fake_data)
    assert signals == []
    assert calls == ["FOO.NS", "BAR.NS"]


def test_scan_universe_calls_entry_fn_for_wired_strategies():
    fired = sr.StrategyDef(
        name="test_only_strategy",
        asset_class=sr.AssetClass.EQUITY_INTRADAY,
        category=sr.TradeCategory.BUY,
        timeframe="5m",
        status=sr.StrategyStatus.LIVE,
        entry_fn=lambda data: {"reason": "always_fires"} if data["symbol"] == "FOO.NS" else None,
        evidence="unit test fixture only",
    )
    original = list(sr.REGISTRY)
    sr.REGISTRY.append(fired)
    try:
        signals = sr.scan_universe(["FOO.NS", "BAR.NS"], lambda sym: {"symbol": sym})
    finally:
        sr.REGISTRY[:] = original

    assert len(signals) == 1
    assert signals[0]["symbol"] == "FOO.NS"
    assert signals[0]["strategy"] == "test_only_strategy"


# ---- category / metrics / leaderboard (2026-09-29 addition) -----------------

def test_every_strategy_has_a_category():
    for strat in sr.REGISTRY:
        assert isinstance(strat.category, sr.TradeCategory)


def test_strategies_by_category_filters_correctly():
    shorts = sr.strategies_by_category(sr.TradeCategory.SHORT_SELL)
    assert len(shorts) >= 5
    assert all(s.category == sr.TradeCategory.SHORT_SELL for s in shorts)


def test_is_viable_none_when_no_metrics():
    strat = sr.StrategyDef(
        name="no_metrics_yet", asset_class=sr.AssetClass.EQUITY_INTRADAY,
        category=sr.TradeCategory.BUY, timeframe="5m", status=sr.StrategyStatus.RESEARCH,
        evidence="fixture",
    )
    assert strat.is_viable() is None


def test_is_viable_false_for_every_short_sell_candidate():
    # 2026-09-29: as of this commit every short-sell strategy tried this
    # session is below PFNET_LIVE_FLOOR - see strategy_registry.py's own
    # module docstring on why "ranked" must never be mistaken for
    # "viable". This test locks that fact down so a future entry can't
    # silently flip it without the test forcing a look.
    shorts = sr.strategies_by_category(sr.TradeCategory.SHORT_SELL)
    assert shorts, "expected at least one registered short-sell strategy"
    assert all(s.is_viable() is False for s in shorts)


def test_gap_and_go_swing_is_the_only_viable_strategy_in_the_registry():
    viable = [s.name for s in sr.REGISTRY if s.is_viable() is True]
    assert viable == ["gap_and_go_swing"]


def test_leaderboard_ranks_by_pfnet_descending():
    board = sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=5)
    assert len(board) == 5
    pfnets = [row["pfnet"] for row in board]
    assert pfnets == sorted(pfnets, reverse=True)
    assert board[0]["name"] == "range_short_target_cluster"  # PFnet 0.26, the best short candidate


def test_leaderboard_marks_every_row_viable_or_not():
    board = sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=5)
    for row in board:
        assert row["viable"] is False  # none clear breakeven yet


def test_leaderboard_never_pads_with_fabricated_entries():
    # No futures/options strategies are registered (no execution path
    # exists for either asset class) - the leaderboard must return an
    # empty list, never invent placeholder rows.
    assert sr.leaderboard(sr.TradeCategory.FUTURES, top_n=5) == []
    assert sr.leaderboard(sr.TradeCategory.OPTIONS, top_n=5) == []


def test_leaderboard_returns_fewer_than_top_n_when_pool_is_smaller():
    board = sr.leaderboard(sr.TradeCategory.BUY, top_n=5)
    assert 0 < len(board) < 5
