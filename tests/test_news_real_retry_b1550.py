"""B-1550 (user 2026-11-11 IST: "Yes retry. Only if the confidence of trade entry is good enough"): one extra real
attempt for LENSKART's in-session paper news long, only while the news is confirmed + confident with a live tick."""
import time
from unittest.mock import patch

import main
from tests.test_news_trades_b1541 import CALM, GOOD2, _agg, _conn

TAG = main.NEWS_TRADE_TAGS["long"]


def _seed(c, sym="LENSKART.NS"):
    c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price, open_reason, publishers_n) "
              "VALUES (?, 'long', ?, ?, 718.05, 696.51, 'upgrade confirmed by a, b (re-based in session)', 2)",
              (sym, TAG, time.time() - 3600))


def test_no_retry_when_confidence_is_not_good_enough():
    c, t = _conn(), time.time()
    _seed(c)
    with patch.object(main, "_news_real_open", return_value=True) as ro:
        main._news_trades_step(c, "LENSKART.NS", _agg(CALM), t, 720.0)
    ro.assert_not_called()
    assert main.NEWS_REAL_RETRY_MARK not in c.execute("SELECT open_reason FROM news_trades").fetchone()[0]


def test_no_retry_without_a_live_tick():
    c, t = _conn(), time.time()
    _seed(c)
    with patch.object(main, "_news_real_open", return_value=True) as ro:
        assert main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), t, 0.0) == []
    ro.assert_not_called()


def test_retry_once_on_confirmed_news_resets_entry_to_live_price():
    c, t = _conn(), time.time()
    _seed(c)
    with patch.object(main, "_news_real_open", return_value=True) as ro:
        acts = main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), t, 720.0)
    assert acts == [("LENSKART.NS", "long", "real_retry"), ("LENSKART.NS", "long", "real_open")]
    assert ro.call_args[0][3] == 720.0 and ro.call_args[0][4] == 698.4
    r = c.execute("SELECT * FROM news_trades").fetchone()
    assert r["entry_price"] == 720.0 and r["stop_price"] == 698.4 and main.NEWS_REAL_RETRY_MARK in r["open_reason"]


def test_skipped_retry_is_never_repeated():
    c, t = _conn(), time.time()
    _seed(c)
    with patch.object(main, "_news_real_open", return_value=False) as ro:
        main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), t, 720.0)
        main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), t, 721.0)
    assert ro.call_count == 1
    r = c.execute("SELECT * FROM news_trades").fetchone()
    assert r["status"] == "open" and r["entry_price"] == 718.05   # paper trade carries on unchanged


def test_other_symbols_keep_the_one_attempt_rule():
    c, t = _conn(), time.time()
    _seed(c, "XYZ.NS")
    with patch.object(main, "_news_real_open", return_value=True) as ro:
        main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 720.0)
    ro.assert_not_called()
