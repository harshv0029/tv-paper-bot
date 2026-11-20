"""B-1645: a real swing exit outside the NSE session keeps the row and its SL and logs one deferral."""
import datetime as dt
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _ts(y, m, d, hh, mm):
    return (dt.datetime(y, m, d, hh, mm) - dt.timedelta(hours=5, minutes=30)).replace(tzinfo=dt.timezone.utc).timestamp()


def _db_with_row():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    conn = main.get_db()
    conn.execute(
        "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, "
        "day, stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 1, 100.0, "
        "'E1', ?, '2026-11-18', 90.0, 'SL1', 90.0, 'macddiv')", (main.time.time(),))
    conn.commit()
    return conn


def test_session_window():
    assert main._real_swing_exit_session_open(_ts(2026, 11, 19, 10, 0))
    assert not main._real_swing_exit_session_open(_ts(2026, 11, 19, 0, 12))   # the ADANIENSOL case
    assert not main._real_swing_exit_session_open(_ts(2026, 11, 19, 15, 30))
    assert not main._real_swing_exit_session_open(_ts(2026, 11, 22, 10, 0))   # Sunday


def test_off_session_exit_keeps_row_and_sl_and_logs_once():
    main._swing_exit_deferred_day.clear()
    with closing(_db_with_row()) as conn, \
            patch("main._real_swing_exit_session_open", return_value=False), \
            patch("main._log_real_order_event") as log, \
            patch("kotak_real_orders.cancel_real_order") as cancel, \
            patch("kotak_real_orders.place_real_exit") as sell:
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="macddiv max_hold_timeout")
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="macddiv max_hold_timeout")
        cancel.assert_not_called()
        sell.assert_not_called()
        assert conn.execute("SELECT sl_order_id FROM real_positions_swing").fetchone()["sl_order_id"] == "SL1"
        events = [c.args[3] for c in log.call_args_list]
        assert events == ["exit_deferred_off_session"]


def test_in_session_exit_still_sells():
    with closing(_db_with_row()) as conn, \
            patch("main._real_swing_exit_session_open", return_value=True), \
            patch("main._kotak_swing_symbol_still_held", return_value=True), \
            patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
            patch("kotak_real_orders.place_real_exit",
                  return_value={"ok": True, "qty": 1, "fill_price": 95.0, "order_id": "X1",
                                "fill_price_confirmed": True}) as sell:
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="t")
        sell.assert_called_once_with("TESTSTOCK-EQ", 1)
