"""B-1762: real positions are not sold in tranches (each sell day is a Rs23.60 DP charge per ISIN)."""
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
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, "
        "sl_order_id, exit_legs_json) VALUES ('TSTX.NS', 'TSTX-EQ', 4, 100.0, 'E1', ?, '2026-11-27', "
        "'SL1', ?)", (main.time.time(), '[{"leg": "t1", "qty": 2, "target_price": 105.0, "status": "open", '
                                           '"r_multiple": "1R"}]'))
    conn.commit()
    return conn


def test_flag_off_by_default():
    assert main.REAL_TRANCHE_EXITS_ENABLED is False


def test_paper_leg_booking_sends_no_real_partial_sell():
    statuses = []
    with closing(_db()) as conn, \
            patch("main._log_real_attempt", side_effect=lambda c, s, side, st, **k: statuses.append(st)), \
            patch("kotak_real_orders.cancel_real_order") as cancel, \
            patch("kotak_real_orders.place_real_exit") as sell:
        main._maybe_place_real_partial_exit(conn, "TSTX.NS", {"leg": "t1"})
        sell.assert_not_called()
        cancel.assert_not_called()  # full-qty SL stays resting
        assert conn.execute("SELECT qty FROM real_positions").fetchone()["qty"] == 4
    assert statuses == ["skipped_tranche_exit_disabled"]
