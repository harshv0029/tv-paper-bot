"""Tests for the Gap and Go swing engine's real-order mirroring
(2026-09-22 build): _maybe_place_real_swing_entry, _maybe_place_real_swing_
exit, _maybe_sync_real_swing_stop_loss, and the is_real_swing_trading_
enabled gate. Mirrors the intraday engine's own real-order test
conventions (see tests/test_sl_before_target_sequencing.py) but against
the swing-specific real_positions_swing table, which has no target leg
and stores the intended stop_loss separately from the confirmed
sl_trigger_price so a failed-SL retry uses the right level."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_gate_is_independent_of_intraday_and_fo_gates():
    for var in ("REAL_TRADING_ENABLED", "REAL_FO_TRADING_ENABLED", "REAL_SWING_TRADING_ENABLED"):
        os.environ.pop(var, None)
    assert main.is_real_swing_trading_enabled() is False
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    os.environ["REAL_FO_TRADING_ENABLED"] = "YES"
    try:
        assert main.is_real_swing_trading_enabled() is False
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        assert main.is_real_swing_trading_enabled() is True
    finally:
        for var in ("REAL_TRADING_ENABLED", "REAL_FO_TRADING_ENABLED", "REAL_SWING_TRADING_ENABLED"):
            os.environ.pop(var, None)


def _entry_patches(sl_ok=True, entry_ok=True):
    return [
        patch("kotak_live_feed.get_live_ticks",
              return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}),
        patch("main.get_scheduler_capital_inr", return_value=1_000_000.0),
        patch("main._real_today_spent_inr", return_value=0.0),
        patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}),
        patch("kotak_real_orders.place_real_entry",
              return_value={"ok": entry_ok, "qty": 10, "fill_price": 100.0, "order_id": "E1",
                            "fill_price_confirmed": True, "detail": "rejected"}),
        patch("kotak_real_orders.place_real_stop_loss",
              return_value={"ok": sl_ok, "order_id": "SL1", "trigger_price": 90.0, "detail": "rejected"}),
    ]


def _apply(patches):
    started = [p.start() for p in patches]
    return started, patches


def _stop(patches):
    for p in patches:
        p.stop()


def test_entry_noop_when_gate_off():
    _fresh_db()
    os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
    patches = _entry_patches()
    _apply(patches)
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is None
            attempt = conn.execute("SELECT * FROM real_trades WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert attempt is None  # "expected default state" - not even logged as an attempt
    finally:
        _stop(patches)


def test_entry_creates_real_position_and_stores_intended_stop_loss():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = _entry_patches(sl_ok=True)
    _apply(patches)
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
            assert row["qty"] == 10
            assert row["entry_price"] == 100.0
            assert row["stop_loss"] == 90.0  # the INTENDED level, independent of sl_trigger_price
            assert row["sl_order_id"] == "SL1"
            assert row["sl_trigger_price"] == 90.0
            assert row["strategy"] == "gap_and_go"
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        _stop(patches)


def test_entry_survives_sl_placement_failure_with_stop_loss_still_stored():
    """The bug this guards against: a naive retry that used entry_price
    instead of the stored stop_loss would rest a nonsensical/immediately-
    triggering stop. Confirms the row keeps the correct intended level
    even when the first SL placement attempt fails."""
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = _entry_patches(sl_ok=False)
    _apply(patches)
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
            assert row["sl_order_id"] is None
            assert row["stop_loss"] == 90.0  # preserved for the retry, NOT the entry price (100.0)
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        _stop(patches)


def test_entry_records_nothing_when_broker_rejects_entry():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = _entry_patches(entry_ok=False)
    _apply(patches)
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is None
            attempt = conn.execute(
                "SELECT * FROM real_trades WHERE symbol = 'TESTSTOCK.NS' AND status = 'failed'"
            ).fetchone()
            assert attempt is not None
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        _stop(patches)


def test_sl_retry_uses_stored_stop_loss_not_entry_price():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, stop_loss, strategy) "
            "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-22', 90.0, 'gap_and_go')",
            (main.time.time(),),
        )
        conn.commit()
        with patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL2", "trigger_price": 90.0}) as mock_sl:
            main._maybe_sync_real_swing_stop_loss(conn)
            mock_sl.assert_called_once_with("TESTSTOCK-EQ", 10, 90.0)
        row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
        assert row["sl_order_id"] == "SL2"


def test_exit_noop_when_no_real_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS")  # must not raise


def test_exit_cancels_sl_and_closes_real_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) "
            "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-22', 90.0, 'SL1', 90.0, 'gap_and_go')",
            (main.time.time(),),
        )
        conn.commit()
        with patch("main._kotak_symbol_still_open", return_value=True), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}) as mock_cancel, \
             patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": True, "qty": 10, "fill_price": 95.0, "order_id": "X1",
                                 "fill_price_confirmed": True}) as mock_exit:
            main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS")
            mock_cancel.assert_called_once_with("SL1")
            mock_exit.assert_called_once_with("TESTSTOCK-EQ", 10)
        row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
        assert row is None


def test_exit_clears_stale_row_without_reselling_when_already_closed_at_broker():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, stop_loss, strategy) "
            "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-22', 90.0, 'gap_and_go')",
            (main.time.time(),),
        )
        conn.commit()
        with patch("main._kotak_symbol_still_open", return_value=False), \
             patch("kotak_real_orders.place_real_exit") as mock_exit:
            main._maybe_place_real_swing_exit(conn, "TESTSTOCK.NS")
            mock_exit.assert_not_called()
        row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
        assert row is None
