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
