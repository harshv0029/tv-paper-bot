"""B-1539: View 5 news monitor - shadow log of news verdicts, scoring, stats, durability, no order effect."""
import sqlite3
import time
from contextlib import closing

import main
import news_signals as ns


def _db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    monkeypatch.setattr(main, "DB_PATH", p, raising=False)
    monkeypatch.setattr(main, "get_db", lambda: _conn(p))
    with closing(_conn(p)) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short"):
            c.execute(f"CREATE TABLE {t} (symbol TEXT PRIMARY KEY, qty INTEGER, entry_price REAL)")
        c.execute("CREATE TABLE entry_funnel_events (bucket_ts REAL, last_ts REAL, kind TEXT, strategy TEXT, side TEXT, symbol TEXT, status TEXT, flag TEXT, slot TEXT, n INTEGER)")
        c.execute(_ddl())
        c.commit()
    return p


def _conn(p):
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    return c


def _ddl():
    src = open("main.py").read()
    i = src.index("CREATE TABLE IF NOT EXISTS news_signal_events")
    return src[i:src.index('"""', i)]


BAD = {"score": -0.7, "n": 3, "hard_neg": [("fraud", "XYZ fraud probe")], "hard_pos": [], "top": [{"title": "XYZ fraud probe"}]}
CALM = {"score": 0.0, "n": 1, "hard_neg": [], "hard_pos": [], "top": []}
MS = {"market": CALM, "sectors": {}}


def _patch_news(monkeypatch, per_symbol):
    monkeypatch.setattr(ns, "entry_verdict", lambda s, d, sector=None, ms=None: (
        {"action": "avoid", "reason": "hard negative", "stock": BAD} if per_symbol.get(s) == "bad" and d == "long"
        else {"action": "allow", "reason": "no adverse news", "stock": CALM}))
    monkeypatch.setattr(ns, "exit_verdict", lambda s, d: (
        {"action": "tighten", "reason": "hard adverse", "stock": BAD} if per_symbol.get(s) == "bad" and d == "long"
        else {"action": "hold", "reason": "none", "stock": CALM}))
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {})


def test_candidates_cover_every_category_and_dedupe(tmp_path, monkeypatch):
    p = _db(tmp_path, monkeypatch)
    now = time.time()
    with closing(_conn(p)) as c:
        c.execute("INSERT INTO entry_funnel_events VALUES (?,?,?,?,?,?,?,?,?,1)", (now, now, "reject", "gap_and_go", "B", "AAA.NS", "skipped_low_balance", "money", ""))
        c.execute("INSERT INTO entry_funnel_events VALUES (?,?,?,?,?,?,?,?,?,1)", (now, now, "placed", "gap_and_go", "B", "BBB.NS", "confirmed", "", ""))
        c.execute("INSERT INTO entry_funnel_events VALUES (?,?,?,?,?,?,?,?,?,1)", (now, now, "reject", "fade", "S", "CCC.NS", "skipped_x", "other", ""))
        c.execute("INSERT INTO entry_funnel_events VALUES (?,?,?,?,?,?,?,?,?,1)", (now - 3 * 86400, now - 3 * 86400, "reject", "old", "B", "OLD.NS", "x", "", ""))
        for t, s in (("real_positions", "L1.NS"), ("real_positions_short", "S1.NS"), ("real_positions_swing", "L2.NS"), ("real_positions_swing_short", "S2.NS")):
            c.execute(f"INSERT INTO {t} VALUES (?,?,?)", (s, 1, 100.0))
        c.commit()
        cands = main._news_monitor_candidates(c, "2026-11-10", now)
        got = {(x[0], x[1], x[2], x[3]): x for x in cands}
        assert ("AAA.NS", "long", "entry", "gap_and_go") in got and got[("BBB.NS", "long", "entry", "gap_and_go")][4] == 1
        assert ("CCC.NS", "short", "entry", "fade") in got and not any(x[0] == "OLD.NS" for x in cands)
        assert {("L1.NS", "long", "exit", "buy"), ("S1.NS", "short", "exit", "short"), ("L2.NS", "long", "exit", "swing"),
                ("S2.NS", "short", "exit", "swing_short")} <= set(got)
        _patch_news(monkeypatch, {"AAA.NS": "bad", "L1.NS": "bad"})
        monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 0.0)
        monkeypatch.setattr(main, "NEWS_MONITOR_MAX_PER_PASS", 50)
        assert main._news_monitor_log(c, cands, "2026-11-10", now, ms=MS) == 7
        rows = {(r["symbol"], r["kind"]): r for r in c.execute("SELECT * FROM news_signal_events")}
        assert rows[("AAA.NS", "entry")]["action"] == "avoid" and rows[("AAA.NS", "entry")]["headline"] == "XYZ fraud probe"
        assert rows[("L1.NS", "exit")]["action"] == "tighten" and rows[("L1.NS", "exit")]["ref_price"] == 100.0  # entry price fallback
        assert rows[("BBB.NS", "entry")]["real_entry"] == 1 and all(r["mode"] == "shadow" for r in rows.values())
        again = main._news_monitor_candidates(c, "2026-11-10", now + 60)
        assert again == []  # logged once a day; a "hold" is only re-checked after an hour
        later = main._news_monitor_candidates(c, "2026-11-10", now + main.NEWS_EXIT_RECHECK_SECONDS + 1)
        assert {x[0] for x in later} == {"S1.NS", "L2.NS", "S2.NS"}  # the tightened L1 is not downgraded


def test_evaluate_scores_long_and_short_and_leaves_no_price_pending(tmp_path, monkeypatch):
    p = _db(tmp_path, monkeypatch)
    old = time.time() - 30 * 3600
    with closing(_conn(p)) as c:
        ins = "INSERT INTO news_signal_events (ts, day, symbol, direction, kind, action, ref_price) VALUES (?,?,?,?,?,?,?)"
        c.execute(ins, (old, "d", "A.NS", "long", "entry", "avoid", 100.0))     # fell 5% -> avoid right, saved 5
        c.execute(ins, (old, "d", "B.NS", "long", "entry", "allow", 100.0))     # rose 2% -> allow right
        c.execute(ins, (old, "d", "C.NS", "short", "exit", "tighten", 100.0))   # rose 4% against the short -> right
        c.execute(ins, (old, "d", "D.NS", "long", "entry", "avoid", 100.0))     # rose 3% -> avoid wrong, cost 3
        c.execute(ins, (old, "d", "E.NS", "long", "entry", "avoid", 100.0))     # no price -> pending
        c.execute(ins, (time.time(), "d2", "F.NS", "long", "entry", "avoid", 100.0))  # too fresh
        c.commit()
        px = {"A.NS": 95.0, "B.NS": 102.0, "C.NS": 104.0, "D.NS": 103.0, "E.NS": 0.0, "F.NS": 50.0}
        assert main._news_monitor_evaluate(c, time.time(), price_fn=lambda s: px[s]) == 4
        r = {x["symbol"]: x for x in c.execute("SELECT * FROM news_signal_events")}
        assert (r["A.NS"]["correct"], r["A.NS"]["move_pct"]) == (1, -5.0) and r["B.NS"]["correct"] == 1
        assert (r["C.NS"]["correct"], r["C.NS"]["move_pct"]) == (1, -4.0) and r["D.NS"]["correct"] == 0
        assert r["E.NS"]["correct"] is None and r["F.NS"]["eval_ts"] is None
        st = main._news_monitor_stats([dict(x) for x in r.values()])
        assert st["entry_avoid"] == {"total": 4, "scored": 2, "correct": 1, "accuracy_pct": 50.0, "saved_pct": 2.0, "avg_move_pct": -1.0}
        assert st["exit_tighten"]["accuracy_pct"] == 100.0 and st["exit_tighten"]["saved_pct"] == 4.0
        assert st["entry_caution"]["accuracy_pct"] is None


def test_view_endpoint_and_page(tmp_path, monkeypatch):
    p = _db(tmp_path, monkeypatch)
    with closing(_conn(p)) as c:
        c.execute("INSERT INTO news_signal_events (ts, day, symbol, direction, kind, action, ref_price, headline) VALUES (?,?,?,?,?,?,?,?)",
                  (time.time(), main.ist_now().strftime("%Y-%m-%d"), "A.NS", "long", "entry", "avoid", 100.0, "<script>x</script>"))
        c.commit()
    monkeypatch.setattr(ns, "market_and_sector_scores", lambda: {"market": CALM, "sectors": {}, "headlines": 0})
    out = main.news_monitor_view(days=30)
    assert out["events"][0]["symbol"] == "A.NS" and out["caused"] == [] and out["live_rules"] == []
    assert out["stats"]["entry_avoid"]["total"] == 1 and "ts_ist" in out["events"][0]
    page = open("static/trade-view5.html").read()
    assert "/news-monitor" in page and "esc(r.headline)" in page  # headlines are untrusted text: always escaped
    assert 'data-src="/trade-view5"' in open("static/trade-view-tabs.html").read()
    assert main.trade_view5().path == "static/trade-view5.html"


def test_shadow_only_durable_and_never_runs_in_tests():
    src = open("main.py").read()
    assert "news_signal_events" in main._GENERIC_MIRROR_TABLES  # survives a Render restart
    assert main._news_monitor_kick() is False  # no background thread under pytest
    block = src[src.index("NEWS_MONITOR_EVERY_N_TICKS = 10"):src.index('@app.get("/real-protection-status")')]
    for banned in ("place_real", "_maybe_place_real", "cancel_", "kotak_real_orders", "_log_real_order_event", "modify_order"):
        assert banned not in block, banned  # the monitor reads and logs; it has no path to an order
    outside = src.replace(block, "")
    assert outside.count("news_signals.") == 0 and outside.count("_news_monitor_kick()") == 1  # only the tick hook
