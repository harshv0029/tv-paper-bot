"""Tests for the strategy registry scaffold (2026-09-28, design-only -
see strategy_registry.py's own module docstring). This module is not
wired into main.py's live path; these tests only cover the scaffold's
own bookkeeping logic."""
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
