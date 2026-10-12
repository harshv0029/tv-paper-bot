import main
import strategy_registry as sr


def test_every_viable_registry_strategy_is_listed():
    names = {r["registry_name"] for r in main.strategy_scan_activity(include_unwired=True)["strategies"]}
    for cat in sr.TradeCategory:
        for e in sr.viable_leaderboard(cat):
            assert e["name"] in names, e["name"]


def test_status_and_counts_b779():
    d = main.strategy_scan_activity(include_unwired=True)
    rows = d["strategies"]
    assert all(r["status"] in ("live_wired", "research_only") for r in rows)
    c = d["counts"]
    assert c["viable_total"] == len(rows) == c["live_wired"] + c["research_only"]
    assert all((r["status"] == "live_wired") == (r["scan_wired"] is True) for r in rows)
    assert all("n_trades" in r and "win_rate_pct" in r for r in rows)
    ro = [r for r in rows if r["status"] == "research_only"]
    assert ro
    for r in ro:
        assert r["strategy_tag"] not in main._STRATEGY_TAG_TO_REGISTRY_NAME
        assert main._is_strategy_viable_for_real_money(r["strategy_tag"]) is False
