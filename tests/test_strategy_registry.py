"""Tests for the strategy registry + leaderboard (2026-09-28, extended
2026-09-29 - see strategy_registry.py's own module docstring). This
module is not wired into main.py's live path; these tests only cover
the scaffold's own bookkeeping/ranking logic."""
import dataclasses

import strategy_registry as sr


def test_registry_names_are_unique():
    names = [s.name for s in sr.REGISTRY]
    assert len(names) == len(set(names))


def test_live_strategies_match_known_live_engines():
    # 2026-09-28: fixed after discovering gap_and_go_swing is ALSO live
    # (both paper and real) on SWING_WATCHLIST - this registry's first
    # version incorrectly listed universal_score as the only live one.
    # 2026-09-30: minervini_vcp_livermore_confirmed wired into
    # _run_swing_scan ("Wire the viable ones" - PFnet 2.043, clears the
    # floor), then power_play_high_tight_flag too ("Wire it now anyway" -
    # explicit override of its own thin-sample caution). 2026-10-01:
    # primary_base too ("wire to live real money only to viable ones" -
    # PFnet 2.069). "status=live" here means "wired into the scan/
    # scheduler", NOT "currently allowed to place a real order" -
    # universal_score is LIVE but blocked by the separate PFnet>=1
    # real-money gate.
    live_names = {s.name for s in sr.strategies_by_status(sr.StrategyStatus.LIVE)}
    assert live_names == {
        "universal_score", "gap_and_go_swing", "minervini_vcp_livermore_confirmed",
        "power_play_high_tight_flag", "primary_base",
        # 2026-10-10 MCX daily engine cells (main._MCX_DAILY_CELLS)
        "sma_crossover__gc__long__1d__atrnone__v1",
        "keltner_channel_breakout__si__long__1d__atrnone__v1",
        "supertrend__si__long__1d__atrnone__v1",
        "sma_crossover__ng__short__1d__atrnone__v1",
        "sector_rotation__momentum_n200__long__1d__atr6d0_h20_l5_n1__v1",
    }


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
        categories=(sr.TradeCategory.BUY,),
        timeframe="5m",
        status=sr.StrategyStatus.LIVE,
        entry_fn=lambda data: {"reason": "always_fires"} if data["symbol"] == "FOO.NS" else None,
        # PFnet well above any registered strategy so the fixture stays inside BUY's
        # top-N however many research variants get registered later.
        metrics=sr.Metrics(pfnet=99.0, pfgross=99.0, win_rate_pct=50.0, n_trades=1),
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

def test_every_strategy_has_at_least_one_category():
    for strat in sr.REGISTRY:
        assert strat.categories
        assert all(isinstance(c, sr.TradeCategory) for c in strat.categories)


def test_strategies_by_category_filters_correctly():
    shorts = sr.strategies_by_category(sr.TradeCategory.SHORT_SELL)
    assert len(shorts) >= 5
    assert all(sr.TradeCategory.SHORT_SELL in s.categories for s in shorts)


def test_a_strategy_can_appear_in_more_than_one_categorys_leaderboard():
    # CLAUDE.md, 2026-09-29 thumb rule: a strategy is not confined to one
    # TradeCategory - categories is a tuple for exactly this reason.
    dual = sr.StrategyDef(
        name="dual_category_fixture_only", asset_class=sr.AssetClass.EQUITY_INTRADAY,
        categories=(sr.TradeCategory.BUY, sr.TradeCategory.SWING),
        timeframe="5m", status=sr.StrategyStatus.RESEARCH,
        metrics=sr.Metrics(pfnet=0.5, pfgross=1.0, win_rate_pct=40.0, n_trades=10),
        evidence="fixture",
    )
    original = list(sr.REGISTRY)
    sr.REGISTRY.append(dual)
    try:
        assert dual in sr.strategies_by_category(sr.TradeCategory.BUY)
        assert dual in sr.strategies_by_category(sr.TradeCategory.SWING)
    finally:
        sr.REGISTRY[:] = original


def test_max_strategy_checks_per_symbol_per_cycle_scales_with_category_count():
    # CLAUDE.md, 2026-09-29 thumb rule (category count updated 2026-10-05
    # with TradeCategory.BIDIRECTIONAL's addition): category-count x
    # top-5 leaderboard slots each bounds live per-stock monitoring cost
    # per round-robin cycle, regardless of registry size - the formula is
    # meant to scale automatically with len(TradeCategory), not stay
    # pinned at its original 5-category value of 25. Locks the FORMULA
    # down (len(TradeCategory) * TOP_N_PER_CATEGORY), not a hardcoded
    # number, so this test can't silently drift from what the constant
    # itself is defined to do.
    assert sr.MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE == len(sr.TradeCategory) * sr.TOP_N_PER_CATEGORY
    assert sr.MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE == 30


def test_is_viable_none_when_no_metrics():
    strat = sr.StrategyDef(
        name="no_metrics_yet", asset_class=sr.AssetClass.EQUITY_INTRADAY,
        categories=(sr.TradeCategory.BUY,), timeframe="5m", status=sr.StrategyStatus.RESEARCH,
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
    # 2026-10-10: sector_rotation sweep cells (B-336) are the only viable shorts; research-only.
    assert all(s.is_viable() is False for s in shorts if not s.name.startswith('sector_rotation__'))


def test_gap_and_go_swing_and_power_play_are_the_only_viable_strategies_in_the_registry():
    # 2026-09-30: the Minervini VCP book-refinement trio (Livermore-confirmed
    # entry filter, 2R breakeven exit, 3R breakeven exit - all real-function
    # full-universe validations) join the previously-viable pair, each
    # clearing PFNET_LIVE_FLOOR where the base minervini_trend_template_vcp
    # (chandelier trail, PFnet 0.908) did not. minervini_vcp_scale_in_sizing
    # (PFnet 0.863) was also tried this session and stays non-viable.
    # 2026-10-01: primary_base (PFnet 2.069, docs/minervini_book_notes.txt
    # CHAPTER 11) joins too - this is the "viable set keeps updating as
    # better-validated strategies clear the floor" standing rule working as
    # designed (strategy_registry.py's own 2026-09-29 "ever-growing pool"
    # thumb rule), not a regression to chase back down.
    # 2026-10-05: order_block_delta_long (PFnet 1.062) and
    # volume_profile_poc_bounce_long (PFnet 1.025) join (full-universe daily
    # research runs 37358050173 / 37358062832). Research-only, not wired to
    # any live path, so the real-money gate still fails closed for both.
    # 2026-10-10: sector_rotation__ (B-336) and MCX sweep cells (B-343) are registered research cells.
    viable = [s.name for s in sr.REGISTRY if s.is_viable() is True
              and not s.name.startswith('sector_rotation__') and s.metrics.universe != 'mcx_proxy_single_symbol'
               and getattr(s, 'source', '') != 'scripts/pattern_lab.py']
    assert set(viable) == {
        "gap_and_go_swing", "power_play_high_tight_flag",
        "minervini_vcp_breakeven_2r", "minervini_vcp_breakeven_3r",
        "minervini_vcp_livermore_confirmed", "primary_base",
        "order_block_delta_long", "volume_profile_poc_bounce_long",
        # 2026-10-07: B-26 OB/VP trail sweep variants (runs 37660618012 / 37660625447)
        "order_block_delta__retest__long__1d__trail4d5__v1",
        "order_block_delta__retest__long__1d__trail6d0__v1",
        "volume_profile_poc__bounce__long__1d__trail4d5__v1",
        "volume_profile_poc__bounce__long__1d__trail6d0__v1",
        # 2026-10-07: gap_and_go max-hold variants (run 37572300915, full universe)
        "gap_and_go__swing__long__1d__hold30__v1",
        "gap_and_go__swing__long__1d__hold60__v1",
    }
    assert not any(n.startswith("rsi_reversal__") for n in viable)


def test_leaderboard_ranks_by_pfnet_descending():
    board = sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=5)
    assert len(board) == 5
    pfnets = [row["pfnet"] for row in board]
    assert pfnets == sorted(pfnets, reverse=True)
    # failed_breakout_short (PFnet 0.657, added 2026-09-30) overtook
    # gap_and_go_short_fade (0.557) as the best short-sell candidate - see
    # CLAUDE.md's own "top-5 keeps updating to prefer whichever validated
    # strategy is actually best" standing rule; this test is meant to
    # track that, not pin a specific name forever.
    assert board[0]["name"] == "failed_breakout_short" or board[0]["name"].startswith("sector_rotation__")


def test_leaderboard_marks_every_row_viable_or_not():
    board = sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=5)
    for row in board:
        assert row["viable"] is False or row["name"].startswith("sector_rotation__")


def test_leaderboard_never_pads_with_fabricated_entries():
    # No futures/options strategies are registered (no execution path
    # exists for either asset class) - the leaderboard must return an
    # empty list, never invent placeholder rows.
    # futures holds MCX proxy sweep rows since 2026-10-10; never padded beyond real rows
    assert all(r["name"].split("__")[1] in ("gc","si","cl","ng","hg") for r in sr.leaderboard(sr.TradeCategory.FUTURES, top_n=5))
    assert sr.leaderboard(sr.TradeCategory.OPTIONS, top_n=5) == []


def test_leaderboard_returns_fewer_than_top_n_when_pool_is_smaller():
    pool = [x for x in sr.REGISTRY if sr.TradeCategory.BUY in x.categories and x.metrics is not None]
    board = sr.leaderboard(sr.TradeCategory.BUY, top_n=len(pool) + 5)
    assert 0 < len(board) < len(pool) + 5


# ---- pool keeps growing, only top 5 per category get monitored (2026-09-29) --

def test_top_strategies_for_monitoring_never_exceeds_the_25_check_bound():
    top = sr.top_strategies_for_monitoring()
    names = [s.name for s in top]
    assert len(names) == len(set(names))  # never the same strategy twice
    assert len(top) <= sr.MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE


def test_top_strategies_for_monitoring_matches_each_categorys_own_leaderboard():
    top_names = {s.name for s in sr.top_strategies_for_monitoring()}
    for category in sr.TradeCategory:
        board_names = {row["name"] for row in sr.leaderboard(category, top_n=sr.TOP_N_PER_CATEGORY)}
        assert board_names <= top_names


def test_top_strategies_for_monitoring_deduplicates_a_multi_category_strategy():
    # CLAUDE.md, 2026-09-29 thumb rule: a strategy ranked in more than one
    # category's top 5 still only costs ONE entry_fn call per symbol per
    # cycle, not one per category it occupies.
    dual = sr.StrategyDef(
        name="dual_category_fixture_only", asset_class=sr.AssetClass.EQUITY_INTRADAY,
        categories=(sr.TradeCategory.BUY, sr.TradeCategory.SWING),
        timeframe="5m", status=sr.StrategyStatus.RESEARCH,
        metrics=sr.Metrics(pfnet=5.0, pfgross=1.0, win_rate_pct=40.0, n_trades=10),
        evidence="fixture",
    )
    original = list(sr.REGISTRY)
    sr.REGISTRY.append(dual)
    try:
        names = [s.name for s in sr.top_strategies_for_monitoring()]
        assert names.count("dual_category_fixture_only") == 1
    finally:
        sr.REGISTRY[:] = original


def test_scan_universe_never_calls_entry_fn_for_a_strategy_ranked_outside_top_5():
    # rsi_overbought_fade_70 (PFnet 0.21) ties with range_short_staged_ladder
    # but sorts 6th - just outside SHORT_SELL's top 5. The explicit
    # instruction this test locks down: however big REGISTRY gets, a
    # strategy that isn't currently ranked in some category's top 5 must
    # never fire during monitoring, even if its entry_fn is wired and
    # would otherwise always fire.
    original = list(sr.REGISTRY)
    idx = next(i for i, s in enumerate(sr.REGISTRY) if s.name == "rsi_overbought_fade_70")
    assert idx is not None
    sr.REGISTRY[idx] = dataclasses.replace(
        sr.REGISTRY[idx], entry_fn=lambda data: {"reason": "always_fires"},
    )
    try:
        assert "rsi_overbought_fade_70" not in [s.name for s in sr.top_strategies_for_monitoring()]
        signals = sr.scan_universe(["FOO.NS"], lambda sym: {"symbol": sym})
        assert all(s["strategy"] != "rsi_overbought_fade_70" for s in signals)
    finally:
        sr.REGISTRY[:] = original


def test_scan_universe_calls_entry_fn_for_a_strategy_ranked_in_top_5():
    original = list(sr.REGISTRY)
    # Rank-1 is looked up live: new registrations legitimately displace it.
    top = sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=1)[0]["name"]
    idx = next(i for i, s in enumerate(sr.REGISTRY) if s.name == top)
    sr.REGISTRY[idx] = dataclasses.replace(
        sr.REGISTRY[idx], entry_fn=lambda data: {"reason": "always_fires"},
    )
    try:
        signals = sr.scan_universe(["FOO.NS"], lambda sym: {"symbol": sym})
        assert any(s["strategy"] == top for s in signals)
    finally:
        sr.REGISTRY[:] = original


def test_scan_universe_statuses_filter_further_restricts_the_top_5_pool():
    board_names = {row["name"] for row in sr.leaderboard(sr.TradeCategory.SHORT_SELL, top_n=5)}
    assert board_names, "expected a non-empty short-sell top 5 for this test to mean anything"
    signals = sr.scan_universe(
        ["FOO.NS"], lambda sym: {"symbol": sym}, statuses=(sr.StrategyStatus.LIVE,),
    )
    # None of SHORT_SELL's top 5 are LIVE (all RESEARCH) - restricting to
    # LIVE must never let a RESEARCH-status top-5 strategy's signal through.
    assert all(s["strategy"] not in board_names for s in signals)


# ---- viable_leaderboard: 2026-09-30, "keep only viable ones on trade  ----
# ---- view... I want all that qualify pfnet >= 1, not just top 5"     ----

def test_viable_leaderboard_excludes_anything_below_the_floor():
    for cat in sr.TradeCategory:
        for row in sr.viable_leaderboard(cat):
            assert row["pfnet"] >= sr.PFNET_LIVE_FLOOR
            assert row["viable"] is True


def test_viable_leaderboard_is_not_capped_at_top_n_per_category():
    # Build a fake category-worth of strategies that all clear the floor,
    # well beyond TOP_N_PER_CATEGORY, and confirm every one of them comes
    # back - the whole point of this function versus leaderboard().
    original = list(sr.REGISTRY)
    extra = [
        dataclasses.replace(
            sr.REGISTRY[0],
            name=f"fake_viable_{i}",
            categories=(sr.TradeCategory.BUY,),
            metrics=dataclasses.replace(sr.REGISTRY[0].metrics, pfnet=2.0 + i),
        )
        for i in range(sr.TOP_N_PER_CATEGORY + 5)
    ]
    sr.REGISTRY.extend(extra)
    try:
        board = sr.viable_leaderboard(sr.TradeCategory.BUY)
        fake_names = {s.name for s in extra}
        returned_fake_names = {row["name"] for row in board if row["name"] in fake_names}
        assert returned_fake_names == fake_names
        assert len(board) > sr.TOP_N_PER_CATEGORY
    finally:
        sr.REGISTRY[:] = original


def test_viable_leaderboard_ranked_best_pfnet_first():
    board = sr.viable_leaderboard(sr.TradeCategory.SWING)
    pfnets = [row["pfnet"] for row in board]
    assert pfnets == sorted(pfnets, reverse=True)
    assert [row["rank"] for row in board] == list(range(1, len(board) + 1))


def test_viable_leaderboard_excludes_a_strategy_with_no_metrics_yet():
    original = list(sr.REGISTRY)
    idx = next(i for i, s in enumerate(sr.REGISTRY) if s.name == "universal_score")
    sr.REGISTRY[idx] = dataclasses.replace(sr.REGISTRY[idx], metrics=None)
    try:
        board = sr.viable_leaderboard(sr.TradeCategory.BUY)
        assert all(row["name"] != "universal_score" for row in board)
    finally:
        sr.REGISTRY[:] = original


def test_viable_leaderboard_respects_a_custom_floor():
    # A stricter floor than PFNET_LIVE_FLOOR narrows the result further -
    # swing's own gap_and_go_swing (1.65) clears 1.0 but not 2.0.
    at_default = {row["name"] for row in sr.viable_leaderboard(sr.TradeCategory.SWING)}
    at_stricter = {row["name"] for row in sr.viable_leaderboard(sr.TradeCategory.SWING, floor=2.0)}
    assert "gap_and_go_swing" in at_default
    assert "gap_and_go_swing" not in at_stricter
    assert at_stricter <= at_default
