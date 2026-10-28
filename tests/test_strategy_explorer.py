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


def test_explorer_marks_failed_replay_but_override_still_admits(monkeypatch):
    # B-1398 (user 2026-10-28 "Keep B"): a failed replay is shown in View 1, the View 1 set still decides real money.
    name = "macddiv__line_any__long__1h__atr3_w5__nonovl__v2"
    out = main.strategy_explorer(pf_min=1.4, pf_max=1.5, limit=5000)
    row = next(r for r in out["rows"] if r["name"] == name)
    assert row["replay_failed"] is True and abs(row["replay_pfnet"] - 0.7338) < 1e-6
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: sr.VIABLE_OVERRIDES)
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", {name})
    assert main._viability_verdict(name, check_switch=False) == (True, "override")
