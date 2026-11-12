"""B-1552 (user 2026-11-11 IST: "On negative news the stock should be shorting too"): confirmed + confident bad news
opens a real 1-share INTRADAY short through the short engine; covered by that engine (news close, 15:10 flatten)."""
import datetime as dt
import time
from contextlib import closing
from unittest.mock import patch

import main
from tests.test_swing_ltp_trail_and_nykaa import _db

TAG = main.NEWS_TRADE_TAGS["short"]
SYM = main.WATCHLIST[0]["symbol"]


def _at(h, m):
    return patch.object(main, "ist_now", return_value=dt.datetime(2026, 11, 11, h, m))


def _fill(conn, symbol):
    conn.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                 "opened_at, day, strategy) VALUES (?, 'X-EQ', 1, 100.0, 'o1', 1.0, '2026-11-11', ?)", (symbol, TAG))
    conn.commit()


def test_bad_news_opens_a_real_short_through_the_short_engine():
    _db()
    with closing(main.get_db()) as c, _at(11, 0), patch.object(main, "_maybe_place_real_short_entry",
                                                              side_effect=lambda conn, s: _fill(conn, s)) as ent:
        c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price) VALUES (?, 'short', ?, ?, 100, 103)",
                  (SYM, TAG, time.time()))
        assert main._news_real_open(c, SYM, "short", 100.0, 103.0, time.time()) is True
        ent.assert_called_once()
        st = c.execute("SELECT * FROM signal_state_short WHERE symbol = ?", (SYM,)).fetchone()
        assert st["strategy"] == TAG and st["stop_loss"] == 103.0 and st["qty"] == main.NEWS_REAL_QTY_CAP
        assert c.execute("SELECT mode FROM news_trades").fetchone()[0] == "real"


def test_skipped_short_leaves_no_engine_row():
    _db()
    with closing(main.get_db()) as c, _at(11, 0), patch.object(main, "_maybe_place_real_short_entry"):
        assert main._news_real_open(c, SYM, "short", 100.0, 103.0, time.time()) is False
        assert c.execute("SELECT COUNT(*) FROM signal_state_short").fetchone()[0] == 0


def test_no_short_after_cutoff_or_outside_the_short_engine_or_when_owned():
    _db()
    with closing(main.get_db()) as c, patch.object(main, "_maybe_place_real_short_entry") as ent:
        with _at(14, 31):
            assert main._news_real_open(c, SYM, "short", 100.0, 103.0, time.time()) is False
        with _at(11, 0):
            assert main._news_real_open(c, "NOTWATCHED.NS", "short", 100.0, 103.0, time.time()) is False
            c.execute("INSERT INTO signal_state_short (symbol, day, status, strategy) VALUES (?, '2026-11-11', 'short', 'range_short')", (SYM,))
            c.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                      "opened_at, day, strategy) VALUES (?, 'X-EQ', 1, 100.0, 'o0', 1.0, '2026-11-11', 'range_short')", (SYM,))
            c.commit()  # B-1553: only a REAL short of another strategy blocks; a paper-only owner is taken over
            assert main._news_real_open(c, SYM, "short", 100.0, 103.0, time.time()) is False
        ent.assert_not_called()


def test_news_close_covers_through_the_short_engine_exit():
    _db()
    with closing(main.get_db()) as c, patch.object(main, "_maybe_place_real_short_exit") as ex:
        _fill(c, SYM)
        assert main._news_real_close(c, SYM, "short", "sentiment weak") is True
        assert ex.call_args.kwargs["reason"].startswith("news_exit: sentiment weak")


def test_news_short_is_flattened_before_the_1515_cancel():
    _db()
    with closing(main.get_db()) as c:
        _fill(c, SYM)
    with _at(15, 11):
        assert main._chan_short_flatten_due(SYM)
    with _at(14, 0):
        assert not main._chan_short_flatten_due(SYM)


def test_short_trail_is_pushed_to_the_short_engine_stop():
    from tests.test_news_trades_b1541 import BAD2, _agg
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO news_trades (symbol, direction, tag, mode, opened_ts, entry_price, stop_price, publishers_n, peak_score) "
                  "VALUES (?, 'short', ?, 'real', ?, 100.0, 103.0, 2, 0.5)", (SYM, TAG, time.time()))
        c.execute("INSERT INTO signal_state_short (symbol, day, status, stop_loss, strategy) VALUES (?, '2026-11-11', 'short', 103.0, ?)", (SYM, TAG))
        c.commit()
        with patch.object(main, "_news_late_entry_ok", return_value=True):
            main._news_trades_step(c, SYM, _agg(BAD2), time.time(), 98.0)
        assert c.execute("SELECT stop_price FROM news_trades").fetchone()[0] == 98.5
        assert c.execute("SELECT stop_loss FROM signal_state_short").fetchone()[0] == 98.5
