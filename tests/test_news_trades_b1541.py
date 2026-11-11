"""B-1541: news trade lifecycle (paper) and real exit of holdings on confirmed bad news."""
import sqlite3
import time
from unittest.mock import MagicMock

import main
import news_signals as ns
from tests.test_news_signals_b1537 import NOW, _rss


def _agg(rows):
    return ns.aggregate(ns.parse_rss(_rss(rows)), NOW)


GOOD2 = [("XYZ bags order worth Rs 900 crore", 1, "moneycontrol.com"), ("XYZ surges after it wins order", 1, "business-standard.com")]
GOOD3 = GOOD2 + [("XYZ rallies as it secures order", 1, "livemint.com")]
BAD2 = [("XYZ plunges as SEBI bars promoters", 1, "moneycontrol.com"), ("SEBI bars XYZ promoters; stock slumps", 2, "economictimes.com")]
CALM = [("XYZ board meets on Friday", 1, "moneycontrol.com")]


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    src = open("main.py").read()
    for t in ("news_trades", "news_signal_events"):
        i = src.index(f"CREATE TABLE IF NOT EXISTS {t} (")
        c.execute(src[i:src.index('"""', i)])
    for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short"):
        c.execute(f"CREATE TABLE {t} (symbol TEXT PRIMARY KEY, qty INTEGER, entry_price REAL)")
    return c


def _open(c, d="long"):
    return c.execute("SELECT * FROM news_trades WHERE direction = ? ORDER BY id DESC", (d,)).fetchone()


def test_good_news_opens_long_adds_on_more_confirmation_and_closes_when_sentiment_weakens():
    c, t = _conn(), time.time()
    assert main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 0.0) == []  # no live tick -> nothing
    assert main._news_trades_step(c, "XYZ.NS", _agg(CALM), t, 100.0) == []  # no confirmed news -> nothing
    assert main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 100.0) == [("XYZ.NS", "long", "open")]
    r = _open(c)
    assert (r["entry_price"], r["stop_price"], r["units"], r["mode"], r["tag"]) == (100.0, 97.0, 1, "paper", "news_event__confirmed__long__1d__v1")
    assert main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 101.0) == []  # same news again: no add
    assert main._news_trades_step(c, "XYZ.NS", _agg(GOOD3), t, 104.0) == [("XYZ.NS", "long", "add")]
    r = _open(c)
    assert r["units"] == 2 and r["entry_price"] == 102.0 and r["publishers_n"] == 3
    assert main._news_trades_step(c, "XYZ.NS", _agg(CALM), t + 3600, 105.06) == [("XYZ.NS", "long", "close")]
    r = _open(c)
    assert r["status"] == "closed" and r["close_reason"].startswith("sentiment weak") and r["pnl_pct"] == 2.2  # 3.0 - 0.8 cost


def test_bad_news_opens_short_and_stop_reversal_and_max_hold_close_it():
    c, t = _conn(), time.time()
    assert main._news_trades_step(c, "XYZ.NS", _agg(BAD2), t, 100.0) == [("XYZ.NS", "short", "open")]
    assert _open(c, "short")["stop_price"] == 103.0
    assert main._news_trades_step(c, "XYZ.NS", _agg(BAD2), t, 103.5) == [("XYZ.NS", "short", "close")]
    assert _open(c, "short")["close_reason"].startswith("stop hit") and _open(c, "short")["pnl_pct"] == -4.3
    main._news_trades_step(c, "ABC.NS", _agg(BAD2), t, 100.0)
    acts = main._news_trades_step(c, "ABC.NS", _agg(GOOD2), t, 99.0)  # news reversed: short closes, long opens
    assert ("ABC.NS", "short", "close") in acts and ("ABC.NS", "long", "open") in acts
    main._news_trades_step(c, "DEF.NS", _agg(BAD2), t, 100.0)
    assert main._news_trades_step(c, "DEF.NS", _agg(BAD2), t + 8 * 86400, 99.0) == [("DEF.NS", "short", "close")]
    rows = [dict(r) for r in c.execute("SELECT * FROM news_trades WHERE direction = 'short'")]
    st = main._news_trade_stats(rows)
    assert st["closed"] == 3 and st["open"] == 0 and st["pfnet"] is not None


def test_real_holding_is_exited_only_on_confirmed_news_with_a_live_tick_by_its_own_engine(monkeypatch):
    c, t = _conn(), time.time()
    main._NEWS_ACTIONABLE.clear()
    c.execute("INSERT INTO real_positions_swing VALUES ('XYZ.NS', 5, 100)")
    c.execute("INSERT INTO real_positions_swing VALUES ('CALM.NS', 5, 100)")
    c.execute("INSERT INTO real_positions_short VALUES ('XYZ.NS', 5, 100)")  # bad news is not against a short
    fns = {n: MagicMock() for n in ("_maybe_place_real_exit", "_maybe_place_real_short_exit",
                                    "_maybe_place_real_swing_exit", "_maybe_place_real_swing_short_exit")}
    for n, m in fns.items():
        monkeypatch.setattr(main, n, m)
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 0.0)
    main._news_note_actionable("XYZ.NS", _agg(BAD2), t)
    assert main._news_exit_real_holdings(c, t) == []  # no live tick -> no exit
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 95.0)
    assert main._news_exit_real_holdings(c, t) == [("XYZ.NS", "long", "swing")]
    fns["_maybe_place_real_swing_exit"].assert_called_once()
    assert fns["_maybe_place_real_swing_exit"].call_args[0][1] == "XYZ.NS"
    assert fns["_maybe_place_real_swing_exit"].call_args[1]["reason"].startswith("news_exit: confirmed news against a long")
    assert not fns["_maybe_place_real_exit"].called and not fns["_maybe_place_real_short_exit"].called  # engine ownership
    row = c.execute("SELECT * FROM news_signal_events").fetchone()
    assert (row["symbol"], row["kind"], row["action"], row["mode"]) == ("XYZ.NS", "exit", "exit", "live")
    assert main._news_exit_real_holdings(c, t) == []  # once per symbol per day
    main._NEWS_ACTIONABLE.clear()


def test_news_trades_are_paper_and_durable():
    assert "news_trades" in main._GENERIC_MIRROR_TABLES
    src = open("main.py").read()
    step = src[src.index("def _news_trades_step("):src.index("_NEWS_EXIT_ENGINES = ")]
    for banned in ("_maybe_place_real", "kotak", "_log_real_attempt", "real_positions"):
        assert banned not in step, banned  # paper only: the lifecycle never touches a real order or position
    assert 'data.news_trades' in open("static/trade-view5.html").read() or 'd.news_trades' in open("static/trade-view5.html").read()


def test_view5_publishes_the_news_chain(monkeypatch):
    """B-1542: every decision carries the headlines it was read from, and the feed lists what was read."""
    import json
    c, t = _conn(), time.time()
    main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 100.0)
    ev = json.loads(_open(c)["evidence"])
    assert len(ev) == 2 and ev[0]["title"].startswith("XYZ") and ev[0]["hard"] and ev[0]["link"].startswith("https://")
    main._NEWS_ACTIONABLE.clear()
    main._news_note_actionable("XYZ.NS", _agg(BAD2), t)
    assert "SEBI" in main._NEWS_ACTIONABLE[("XYZ.NS", "long")]["evidence"]
    main._NEWS_ACTIONABLE.clear()
    ns._cache.clear()
    monkeypatch.setattr(ns.time, "time", lambda: NOW)
    monkeypatch.setattr(ns, "_fetch", lambda url: _rss([("Bank Nifty slumps as PSU banks tumble", 1, "moneycontrol.com"), ("Old story", 90, "moneycontrol.com")]))
    f = ns.feed(10, NOW)
    assert len(f) == 1 and f[0]["scopes"] == ["market", "Financial Services"] and f[0]["score"] == -1.0
    ns._cache.clear()
    page = open("static/trade-view5.html").read()
    assert 'id="feed"' in page and "chain(r.evidence)" in page and 'rel="noopener noreferrer"' in page and "/^https:" in page
