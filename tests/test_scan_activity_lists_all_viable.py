import main
import strategy_registry as sr


def test_every_viable_registry_strategy_is_listed():
    names = {r["registry_name"] for r in main.strategy_scan_activity()["strategies"]}
    for cat in sr.TradeCategory:
        for e in sr.viable_leaderboard(cat):
            assert e["name"] in names, e["name"]
