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
    assert all(r["status"] in ("live_wired", "research_only", "wired_gate_closed") for r in rows)
    c = d["counts"]
    assert len(rows) == c["live_wired"] + c["research_only"] + c.get("wired_gate_closed", 0)
    assert all((r["status"] == "live_wired") == (r["scan_wired"] is True) for r in rows if r["status"] != "wired_gate_closed")
    assert all("n_trades" in r and "win_rate_pct" in r for r in rows)
    ro = [r for r in rows if r["status"] == "research_only"]
    assert ro
    for r in ro:
        if r["strategy_tag"] in main.ENVELOPE_LONG_LIVE_CELLS or r["strategy_tag"] in main.CUP_CHEAT_LONG_LIVE_CELLS:
            continue  # B-1264: the n200 research row of a live tag stays its own row; the live gate rides the `_mr` replay row
        assert r["strategy_tag"] not in main._STRATEGY_TAG_TO_REGISTRY_NAME or r["strategy_tag"] in main.REPLAY_OWED_TAGS \
            or r["strategy_tag"] in main.REPLAY_FAILED_TAGS  # B-1396: replayed below floor is also gate-closed
        assert main._is_strategy_viable_for_real_money(r["strategy_tag"]) is False
