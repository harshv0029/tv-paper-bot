"""B-1656: View 5 shows each news trade's real-money outcome (ABB 16-Nov looked like a real holding; its real buy was
skipped_low_balance). Read from real_trades, never a new stored flag."""
import sqlite3
import time
from contextlib import closing

import main
from tests.test_news_monitor_b1539 import _db, _conn, CALM
import news_signals as ns


def _seed(p, opened, rows):
    with closing(_conn(p)) as c:
        c.execute("CREATE TABLE real_trades (id INTEGER PRIMARY KEY, ts REAL, day TEXT, symbol TEXT, kotak_trading_symbol TEXT, "
                  "side TEXT, qty INTEGER, price_est REAL, notional_inr REAL, status TEXT, order_id TEXT, detail TEXT, "
                  "raw_response TEXT, strategy TEXT)")
        c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price, open_reason) VALUES "
                  "('ABB.NS','long',?,?,6866.5,6660.5,'upgrades')", (main.NEWS_TRADE_TAGS["long"], opened))
        c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price, open_reason) VALUES "
                  "('XYZ.NS','short',?,?,100,103,'fraud')", (main.NEWS_TRADE_TAGS["short"], opened - 5))
        for sym, tag, dts, status, detail in rows:
            c.execute("INSERT INTO real_trades (ts, day, symbol, side, status, detail, strategy) VALUES (?,?,?,?,?,?,?)",
                      (opened + dts, "2026-11-16", sym, "B", status, detail, tag))
        c.commit()


def test_skip_reason_is_attached_and_page_labels_paper(tmp_path, monkeypatch):
    p = _db(tmp_path, monkeypatch)
    now = time.time()
    tag = main.NEWS_TRADE_TAGS["long"]
    _seed(p, now, [("ABB.NS", tag, 60, "skipped_low_balance", "1 share = Rs6866.50 - capped to 0"),
                   ("ABB.NS", tag, 4000, "confirmed", "a much later unrelated buy"),       # outside the 15-min window
                   ("ABB.NS", "other_tag", 30, "confirmed", "another strategy")])          # other strategy
    monkeypatch.setattr(ns, "market_and_sector_scores", lambda: {"market": CALM, "sectors": {}, "headlines": 0})
    out = main.news_monitor_view(days=30)
    by = {t["symbol"]: t for t in out["news_trades"]}
    assert by["ABB.NS"]["real_attempt_status"] == "skipped_low_balance" and "6866.50" in by["ABB.NS"]["real_attempt_detail"]
    assert by["XYZ.NS"]["real_attempt_status"] is None
    page = open("static/trade-view5.html").read()
    assert "<b>PAPER</b>" in page and "<b>REAL</b>" in page and "skipped: not enough money" in page
    assert "Paper only: no real order. Real money opens for these only once" not in page  # stale text (B-1543 buys are live)


def test_confirmed_wins_and_missing_table_never_raises(tmp_path, monkeypatch):
    p = _db(tmp_path, monkeypatch)
    now = time.time()
    tag = main.NEWS_TRADE_TAGS["long"]
    _seed(p, now, [("ABB.NS", tag, 10, "failed", "x"), ("ABB.NS", tag, 20, "confirmed", "bought")])
    with closing(_conn(p)) as c:
        t = dict(c.execute("SELECT * FROM news_trades WHERE symbol='ABB.NS'").fetchone())
        assert main._news_real_attempt_for(c, t)["real_attempt_status"] == "confirmed"
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    assert main._news_real_attempt_for(bare, t) == {"real_attempt_status": None, "real_attempt_detail": None}
