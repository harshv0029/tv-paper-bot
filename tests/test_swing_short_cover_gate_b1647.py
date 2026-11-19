"""B-1647: off-session swing-short covers are deferred (row + BUY-stop kept) and retried once a paper exit exists."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    conn = main.get_db()
    conn.execute(
        "INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
        "opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', "
        "1, 100.0, 'E1', ?, '2026-11-18', 110.0, 'SL1', 110.0, 'x')", (main.time.time() - 60,))
    conn.commit()
    return conn


def _paper_exit(conn):
    conn.execute("INSERT INTO short_trades_closed (ts, symbol, qty, entry_price, exit_price, fx_to_inr, pnl_inr, "
                 "exit_reason, strategy) VALUES (?, 'TESTSTOCK.NS', 1, 100, 95, 1, 5, 'max_hold', 'x')", (main.time.time(),))
    conn.commit()


def test_off_session_cover_deferred_once_and_keeps_stop():
    main._swing_exit_deferred_day.clear()
    with closing(_db()) as conn, patch("main._real_swing_exit_session_open", return_value=False), \
            patch("main._log_real_order_event") as log, patch("kotak_real_orders.cancel_real_order") as cancel:
        main._maybe_place_real_swing_short_exit(conn, "TESTSTOCK.NS", reason="r")
        main._maybe_place_real_swing_short_exit(conn, "TESTSTOCK.NS", reason="r")
        cancel.assert_not_called()
        assert [c.args[2:4] for c in log.call_args_list] == [("short_cover", "exit_deferred_off_session")]
        assert conn.execute("SELECT sl_order_id FROM real_positions_swing_short").fetchone()[0] == "SL1"
        assert main._retry_deferred_swing_short_covers(conn) == 0


def test_retry_covers_only_with_paper_exit_on_record():
    with closing(_db()) as conn, patch("main._real_swing_exit_session_open", return_value=True), \
            patch("main._maybe_place_real_swing_short_exit") as cover:
        assert main._retry_deferred_swing_short_covers(conn) == 0   # no paper exit: hold
        cover.assert_not_called()
        _paper_exit(conn)
        assert main._retry_deferred_swing_short_covers(conn) == 1
        assert "max_hold" in cover.call_args.kwargs["reason"]


def test_retry_skips_while_paper_row_open():
    with closing(_db()) as conn, patch("main._real_swing_exit_session_open", return_value=True), \
            patch("main._maybe_place_real_swing_short_exit") as cover:
        _paper_exit(conn)
        conn.execute("DROP TABLE signal_state_swing_short")  # minimal stand-in: only the symbol column is read
        conn.execute("CREATE TABLE signal_state_swing_short (symbol TEXT)")
        conn.execute("INSERT INTO signal_state_swing_short VALUES ('TESTSTOCK.NS')")
        assert main._retry_deferred_swing_short_covers(conn) == 0
        cover.assert_not_called()
