"""B-1372: View 4 counter of entries fired today but rejected by the viability gate."""
import sqlite3

import main


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE real_trades (ts REAL, day TEXT, symbol TEXT, kotak_trading_symbol TEXT, side TEXT, qty INT,"
              " price_est REAL, notional_inr REAL, status TEXT, order_id TEXT, detail TEXT, raw_response TEXT, strategy TEXT)")
    c.execute("CREATE TABLE real_fo_trades (ts REAL, day TEXT, leg_key TEXT, kotak_trading_symbol TEXT, side TEXT, qty INT,"
              " price_est REAL, notional_inr REAL, status TEXT, order_id TEXT, detail TEXT, raw_response TEXT)")
    return c


def test_counts_today_per_strategy_and_ignores_other_rows():
    c = _db()
    day = "2026-10-26"
    for sym in ("TCS.NS", "TCS.NS", "INFY.NS"):
        main._log_real_attempt(c, sym, "B", "skipped_strategy_not_viable", strategy="gap_and_go")
    main._log_real_attempt(c, "SBIN.NS", "S", "skipped_strategy_not_viable", strategy="chan_gap_short")
    main._log_real_attempt(c, "SBIN.NS", "B", "placed", strategy="gap_and_go")
    main._log_real_fo_attempt(c, "NIFTY:STRADDLE-CE", "B", "skipped_strategy_not_viable", detail="strategy_tag=long_straddle")
    main._log_real_fo_attempt(c, "NIFTY:STRADDLE-PE", "B", "skipped_strategy_not_viable", detail="strategy_tag=long_straddle")
    c.execute("UPDATE real_trades SET day = ?", (day,))
    c.execute("UPDATE real_fo_trades SET day = ?", (day,))
    c.execute("INSERT INTO real_trades (day, symbol, side, status, strategy) VALUES ('2026-10-25','X','B',"
              "'skipped_strategy_not_viable','gap_and_go')")
    r = main._viability_rejections_today(c, day)
    assert r["total"] == 6
    by = {(x["strategy"], x["segment"]): x for x in r["by_strategy"]}
    assert by[("gap_and_go", "equity")]["count"] == 3 and by[("gap_and_go", "equity")]["symbols"] == 2
    assert by[("long_straddle", "fo")]["count"] == 2 and by[("long_straddle", "fo")]["symbols"] == 1
    assert by[("chan_gap_short", "equity")]["sides"] == "S"
    assert r["by_strategy"][0]["strategy"] == "gap_and_go"


def test_empty_and_missing_tables_never_raise():
    assert main._viability_rejections_today(_db(), "2026-10-26") == {"day": "2026-10-26", "total": 0, "symbols": 0, "by_strategy": []}
    assert main._viability_rejections_today(sqlite3.connect(":memory:"), "2026-10-26")["total"] == 0


def test_view4_renders_counter():
    html = open("static/trade-view4.html").read()
    assert "rejected_today" in html and "REJECTED by viability" in html


def _stack(c, label):
    c.execute("CREATE TABLE IF NOT EXISTS strategy_viable_stack (id INTEGER PRIMARY KEY, created_at REAL, label TEXT, names TEXT)")
    c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (0, ?, '[]')", (label,))


def test_unlock_hint_gives_loosest_factor_values(monkeypatch):
    """B-1374: per rejected strategy, the 3-factor values that would have admitted it; easiest = fewest changes."""
    import types
    mets = {"reg_a": types.SimpleNamespace(pfnet=1.05, n_trades=500, avg_held_hrs=10.0),
            "reg_b": types.SimpleNamespace(pfnet=0.9, n_trades=40, avg_held_hrs=300.0)}
    monkeypatch.setattr(main, "_STRATEGY_TAG_TO_REGISTRY_NAME", {"tag_a": "reg_a", "tag_b": "reg_b", "tag_c": "reg_c"})
    monkeypatch.setattr(main, "_registry_entry", lambda n: types.SimpleNamespace(metrics=mets[n]) if n in mets else None)
    monkeypatch.setattr(main, "REPLAY_OWED_TAGS", {"tag_b"})
    c = _db()
    _stack(c, "pfnet(1.1-99), min(100), maxhold(100)")
    rej = {"by_strategy": [{"strategy": "tag_b", "segment": "equity", "count": 5},
                           {"strategy": "tag_a", "segment": "equity", "count": 1},
                           {"strategy": "tag_c", "segment": "equity", "count": 2}]}
    h = main._viability_unlock_hint(c, rej)
    by = {e["strategy"]: e for e in h["per_strategy"]}
    assert by["tag_a"]["changes"] == ["pf_min"] and by["tag_a"]["needs"]["pf_min"] == 1.05
    assert set(by["tag_b"]["changes"]) == {"pf_min", "min_trades", "max_hold_hrs"}
    assert by["tag_b"]["fixable"] is True and by["tag_b"]["replay_owed"] is True  # stack membership bypasses replay-owed
    assert by["tag_b"]["needs"]["min_trades"] == 40 and by["tag_b"]["needs"]["max_hold_hrs"] == 300.0
    assert by["tag_c"]["fixable"] is False and by["tag_c"]["note"] == "no registry entry"
    assert h["easiest"]["strategy"] == "tag_a"


def test_unlock_hint_no_stack_or_no_rejections_never_raises():
    assert main._viability_unlock_hint(_db(), {"by_strategy": []})["easiest"] is None
    assert main._viability_unlock_hint(sqlite3.connect(":memory:"), None)["per_strategy"] == []
    html = open("static/trade-view4.html").read()
    assert "unlock_hint" in html and "To let at least 1 more trade in" in html
