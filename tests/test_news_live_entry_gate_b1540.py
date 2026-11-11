"""B-1540: news entry rule LIVE - acts only on confirmed + confident news AND a live tick; 24x7 sweep."""
import time
from unittest.mock import MagicMock

import main
import news_signals as ns
from tests.test_news_signals_b1537 import NOW, _rss


def _agg(rows):
    return ns.aggregate(ns.parse_rss(_rss(rows)), NOW)


TWO_PUBS = [("XYZ plunges as SEBI bars promoters", 1, "moneycontrol.com"), ("SEBI bars XYZ promoters; stock slumps", 2, "economictimes.com")]


def test_confirmation_needs_two_trusted_publishers_and_an_agreeing_score():
    c = ns.confirmation(_agg(TWO_PUBS), "long")
    assert c["actionable"] and c["publishers"] == ["economictimes", "moneycontrol"] and c["event"] == "sebi bars"
    assert not ns.confirmation(_agg(TWO_PUBS), "short")["actionable"]  # bad news is not against a short
    one = ns.confirmation(_agg([TWO_PUBS[0], ("XYZ fraud: stock crashes", 1, "moneycontrol.com")]), "long")
    assert one["confident"] and not one["confirmed"] and not one["actionable"]  # same publisher twice is not confirmation
    blog = ns.confirmation(_agg([("XYZ fraud", 1, "blog.example"), ("XYZ scam", 1, "other.example")]), "long")
    assert not blog["actionable"]  # untrusted publishers never confirm
    mixed = ns.confirmation(_agg(TWO_PUBS + [("Broker upgrades XYZ", 1, "livemint.com")]), "long")
    assert mixed["confirmed"] and not mixed["confident"] and not mixed["actionable"]  # opposing hard event -> not confident
    good = [("XYZ bags order worth Rs 900 crore", 1, "moneycontrol.com"), ("XYZ surges after it wins order", 1, "business-standard.com")]
    assert ns.confirmation(_agg(good), "short")["actionable"] and not ns.confirmation(_agg(good), "long")["actionable"]


def test_gate_blocks_only_with_fresh_actionable_news_and_a_live_tick(monkeypatch):
    main._NEWS_ACTIONABLE.clear()
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 100.0)
    assert main._news_blocks_entry("XYZ.NS", "long") is None  # nothing known -> entry proceeds
    conf = main._news_note_actionable("XYZ.NS", _agg(TWO_PUBS), time.time())
    assert conf["long"]["actionable"] and ("XYZ.NS", "long") in main._NEWS_ACTIONABLE and ("XYZ.NS", "short") not in main._NEWS_ACTIONABLE
    assert "sebi bars" in main._news_blocks_entry("XYZ.NS", "long") and main._news_blocks_entry("XYZ.NS", "short") is None
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 0.0)
    assert main._news_blocks_entry("XYZ.NS", "long") is None  # no live tick -> the module does not act
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 100.0)
    main._NEWS_ACTIONABLE[("XYZ.NS", "long")]["ts"] -= main.NEWS_ACTIONABLE_TTL_S + 1
    assert main._news_blocks_entry("XYZ.NS", "long") is None  # stale finding expires
    main._news_note_actionable("XYZ.NS", _agg(TWO_PUBS), time.time())
    main._news_note_actionable("XYZ.NS", _agg([("XYZ board meets", 1, "moneycontrol.com")]), time.time())
    assert ("XYZ.NS", "long") not in main._NEWS_ACTIONABLE  # a later calm read clears it
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: (_ for _ in ()).throw(RuntimeError("x")))
    main._NEWS_ACTIONABLE[("XYZ.NS", "long")] = {"ts": time.time(), "reason": "r"}
    assert main._news_blocks_entry("XYZ.NS", "long") is None  # never raises, fail-open
    main._NEWS_ACTIONABLE.clear()


def test_gate_logs_the_skip_and_a_live_row(monkeypatch):
    main._NEWS_ACTIONABLE.clear()
    monkeypatch.setattr(main, "_news_live_ltp", lambda s, t=None: 100.0)
    lra = MagicMock()
    monkeypatch.setattr(main, "_log_real_attempt", lra)
    conn = MagicMock()
    assert main._news_gate_entry(conn, "XYZ.NS", "B", "long", "gap_and_go") is False and not lra.called
    main._news_note_actionable("XYZ.NS", _agg(TWO_PUBS), time.time())
    assert main._news_gate_entry(conn, "XYZ.NS", "B", "long", "gap_and_go") is True
    assert lra.call_args[0][1:4] == ("XYZ.NS", "B", "skipped_news_avoid") and "sebi bars" in lra.call_args[1]["detail"]
    sql = conn.execute.call_args[0][0]
    assert "news_signal_events" in sql and "'live'" in sql
    assert main._entry_reject_flag("skipped_news_avoid") == "other"  # one of the three reject flags, never silent
    main._NEWS_ACTIONABLE.clear()


def test_gate_is_wired_into_every_equity_entry_engine_and_no_exit_path():
    src = open("main.py").read()
    def body(name):
        i = src.index(f"def {name}(")
        return src[i:src.index("\ndef ", i + 10)]
    for fn, call in (("_maybe_place_real_entry", '_news_gate_entry(conn, symbol, "B", "long", strategy_tag)'),
                     ("_maybe_place_real_short_entry", '_news_gate_entry(conn, symbol, "S", "short", strategy_tag)'),
                     ("_maybe_place_real_swing_entry", '_news_gate_entry(conn, symbol, "B", "long", strategy)'),
                     ("_maybe_place_real_swing_short_entry", '_news_gate_entry(conn, symbol, "S", "short", strategy)')):
        b = body(fn)
        assert call in b and b.index(call) < b.index("_is_strategy_viable_for_real_money"), fn
    assert src.count("_news_gate_entry(") == 5  # the definition + the four entry engines; no exit / SL / heal path
    for fn in ("_maybe_place_real_exit", "_maybe_place_real_short_exit", "_maybe_place_real_swing_exit"):
        assert "_news" not in body(fn), fn  # exits never consult the news; the news pass calls them from outside


def test_sweep_walks_the_watchlist_round_robin_24x7(monkeypatch):
    main._NEWS_ACTIONABLE.clear()
    seen = []
    monkeypatch.setattr(ns, "stock_items", lambda s, name=None: seen.append(s) or [])
    monkeypatch.setattr(main, "NEWS_SWEEP_PER_PASS", 3)
    monkeypatch.setattr(main, "get_db", lambda: MagicMock())
    monkeypatch.setattr(main, "_news_trades_step", lambda *a, **k: [])
    main._news_sweep_cursor[0] = 0
    syms = ["A.NS", "B.NS", "C.NS", "D.NS"]
    assert main._news_sweep_watchlist(time.time(), syms) == 3 and main._news_sweep_watchlist(time.time(), syms) == 3
    assert seen == ["A.NS", "B.NS", "C.NS", "D.NS", "A.NS", "B.NS"]
    src = open("main.py").read()
    tick = src[src.index("async def _scheduler_tick"):src.index("_news_monitor_kick()  # B-1539")]
    assert "\n    return" not in tick  # nothing returns from the tick before the news kick: it runs outside market hours too
    main._news_sweep_cursor[0] = 0
