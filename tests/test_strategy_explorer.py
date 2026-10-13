import main
import strategy_registry as sr


def test_explorer_filters_match_registry():
    out = main.strategy_explorer(categories="swing", pf_min=1.1, min_n=30, max_hold_hrs=18.75, limit=5000)
    for r in out["rows"]:
        assert "swing" in r["categories"] and r["pfnet"] >= 1.1
        assert r["n_trades"] >= 30 and r["avg_held_hrs"] <= 18.75
    want = {d.name for d in sr.REGISTRY if d.metrics and d.metrics.pfnet >= 1.1
            and (d.metrics.n_trades or 0) >= 30 and d.metrics.avg_held_hrs is not None
            and d.metrics.avg_held_hrs <= 18.75 and sr.TradeCategory.SWING in d.categories}
    assert {r["name"] for r in out["rows"]} == want


def test_explorer_no_filters_returns_all_categories():
    out = main.strategy_explorer(limit=5)
    assert out["total"] >= len(out["rows"]) and len(out["rows"]) == 5
    assert "swing" in out["categories_available"]
