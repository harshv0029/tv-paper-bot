"""B-1553 (user 2026-11-12: Lenskart's one real news retry was blocked by a PAPER sector_rotation swing row): a paper-
only owner no longer blocks a real news entry; the news engine takes the symbol (entry, exit, execution), a REAL
holding of another strategy still blocks, and a failed real entry restores the paper owner."""
import datetime as dt
import time
from contextlib import closing
from unittest.mock import patch

import main
from tests.test_swing_ltp_trail_and_nykaa import _db

LONG = main.NEWS_TRADE_TAGS["long"]
SHORT = main.NEWS_TRADE_TAGS["short"]
SYM = "LENSKART.NS"
PAPER = "sector_rotation__momentum_n200__long__1d__atr6d0_h20_l1_n5__v1"


def _paper_swing(c):
    c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, entry_ts) "
              "VALUES (?, ?, '2026-11-10', 732.3, 690.0, 1, ?)", (SYM, PAPER, time.time()))
    c.commit()


def _fill_swing(conn, symbol, qty, ltp, stop, tag):
    conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                 "stop_loss, strategy) VALUES (?, 'LENSKART-EQ', 1, ?, 0, '2026-11-12', ?, ?)", (symbol, ltp, stop, tag))
    conn.commit()


def _owner(c):
    r = c.execute("SELECT strategy FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
    return r[0] if r else None


def test_paper_owner_is_taken_and_the_real_buy_goes_through():
    _db()
    with closing(main.get_db()) as c, patch.object(main, "_maybe_place_real_swing_entry", side_effect=_fill_swing) as ent:
        _paper_swing(c)
        assert main._news_real_open(c, SYM, "long", 718.0, 696.5, time.time()) is True
        ent.assert_called_once()
        assert _owner(c) == LONG
        log = c.execute("SELECT status, detail FROM real_trades WHERE status = 'news_took_paper_owner'").fetchone()
        assert log and PAPER in log[1]


def test_failed_real_buy_restores_the_paper_owner():
    _db()
    with closing(main.get_db()) as c, patch.object(main, "_maybe_place_real_swing_entry"):
        _paper_swing(c)
        assert main._news_real_open(c, SYM, "long", 718.0, 696.5, time.time()) is False
        r = c.execute("SELECT strategy, entry_price FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
        assert r[0] == PAPER and r[1] == 732.3


def test_real_holding_of_another_strategy_still_blocks():
    _db()
    with closing(main.get_db()) as c, patch.object(main, "_maybe_place_real_swing_entry") as ent:
        _paper_swing(c)
        _fill_swing(c, SYM, 1, 732.3, 690.0, PAPER)
        assert main._news_real_open(c, SYM, "long", 718.0, 696.5, time.time()) is False
        ent.assert_not_called()
        assert _owner(c) == PAPER
        assert c.execute("SELECT status FROM real_trades").fetchone()[0] == "skipped_already_open"


def test_short_takes_a_paper_short_owner():
    _db()
    sym = main.WATCHLIST[0]["symbol"]

    def fill(conn, s):
        conn.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                     "opened_at, day, strategy) VALUES (?, 'X-EQ', 1, 100.0, 'o1', 1.0, '2026-11-12', ?)", (s, SHORT))
        conn.commit()
    with closing(main.get_db()) as c, \
            patch.object(main, "ist_now", return_value=dt.datetime(2026, 11, 12, 11, 0)), \
            patch.object(main, "_maybe_place_real_short_entry", side_effect=fill):
        c.execute("INSERT INTO signal_state_short (symbol, day, status, strategy) VALUES (?, '2026-11-12', 'short', 'range_short')", (sym,))
        c.commit()
        assert main._news_real_open(c, sym, "short", 100.0, 103.0, time.time()) is True
        assert c.execute("SELECT strategy FROM signal_state_short WHERE symbol = ?", (sym,)).fetchone()[0] == SHORT
