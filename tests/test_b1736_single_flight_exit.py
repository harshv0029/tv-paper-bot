"""B-1736: two concurrent real exits for one holding send ONE market SELL (VAML.NS 26-Nov 13:33 IST)."""
import threading
import time
from contextlib import closing
from unittest.mock import patch

import kotak_real_orders
import main
from tests.test_swing_exit_session_gate_b1645 import _db_with_row


def test_concurrent_swing_exits_send_one_sell():
    started, release = threading.Event(), threading.Event()
    sends = []

    def slow_sell(trdsym, qty, *a, **k):
        sends.append((trdsym, qty))
        started.set()
        release.wait(5)
        return {"ok": True, "qty": qty, "fill_price": 95.0, "order_id": "X1", "fill_price_confirmed": True}

    with closing(_db_with_row()):
        pass
    statuses = []
    with patch("main._real_swing_exit_session_open", return_value=True), \
            patch("main._kotak_swing_symbol_still_held", return_value=True), \
            patch("main._close_swing_option_leg"), \
            patch("main._sync_real_positions_swing_external"), \
            patch("main._log_real_order_event"), \
            patch("main._log_real_attempt", side_effect=lambda c, s, side, st, **k: statuses.append(st)), \
            patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
            patch("kotak_real_orders.place_real_exit", side_effect=slow_sell):
        def run(reason):
            with closing(main.get_db()) as c:
                main._maybe_place_real_swing_exit(c, "TESTSTOCK.NS", reason=reason)
        t1 = threading.Thread(target=run, args=("envelope_max_hold_timeout",))
        t1.start()
        assert started.wait(5)
        run("retry of paper swing exit already recorded")  # arrives while the first is still confirming
        release.set()
        t1.join(5)
    assert len(sends) == 1
    assert "skipped_exit_in_flight" in statuses and statuses.count("confirmed") == 1


def test_failed_first_exit_releases_for_retry():
    with closing(_db_with_row()) as conn, \
            patch("main._real_swing_exit_session_open", return_value=True), \
            patch("main._kotak_swing_symbol_still_held", return_value=True), \
            patch("main._close_swing_option_leg"), \
            patch("main._log_real_order_event"), \
            patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
            patch("kotak_real_orders.place_real_exit", return_value={"ok": False, "detail": "x"}) as sell:
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="a")
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="b")
        assert sell.call_count == 2  # no lock left behind after a failure


def test_recent_in_flight_note_blocks_second_sell():
    kotak_real_orders.note_exit_in_flight("TESTSTOCK-EQ", "S", 1, "X9")
    try:
        with closing(_db_with_row()) as conn, \
                patch("main._real_swing_exit_session_open", return_value=True), \
                patch("main._kotak_swing_symbol_still_held", return_value=True), \
                patch("main._close_swing_option_leg"), \
                patch("main._log_real_order_event"), \
                patch("kotak_real_orders.cancel_real_order") as cancel, \
                patch("kotak_real_orders.place_real_exit") as sell:
            main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS", reason="retry")
            sell.assert_not_called()
            cancel.assert_not_called()  # the resting SL is kept
    finally:
        kotak_real_orders.clear_exit_in_flight("TESTSTOCK-EQ", "S")


def test_every_real_exit_engine_is_single_flight():
    for fn in (main._maybe_place_real_exit, main._maybe_place_real_short_exit, main._maybe_place_real_swing_exit,
               main._maybe_place_real_swing_short_exit, main._maybe_place_real_fo_option_exit):
        assert hasattr(fn, "__wrapped__"), fn.__name__
