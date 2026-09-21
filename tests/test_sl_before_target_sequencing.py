"""Tests for SL-before-target real-order sequencing (2026-09-21, explicit
user instruction after a live Cochin Shipyard incident: a resting TARGET
order was placed, then the fresh SL for the same leg got REJECTED,
leaving the position with a profit target but no stop-loss until the
user noticed and manually fixed it by hand. "First after entry, I want
SL order then confirm and then send the target order."

Covers both places a fresh SL+target pair gets placed:
1. _maybe_place_real_entry - the initial entry.
2. _maybe_place_real_partial_exit - advancing to the next staged leg.

In both, the fix is the same: place SL first, and only place/replace the
target if the SL is CONFIRMED - never rest an unprotected target."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _enable_real_trading(conn):
    conn.execute(
        "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
        "VALUES (1, 1, ?, 'test', 'test')", (main.time.time(),),
    )
    conn.commit()


def _insert_paper_signal(conn, symbol, qty=10, stop_loss=90.0, target=130.0):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
        "VALUES (?, '2026-09-21', 'long', 100.0, ?, ?, ?, ?, ?, 1.0, '5m')",
        (symbol, stop_loss, stop_loss, target, qty, main.time.time()),
    )
    conn.commit()


def _run_entry(sl_ok: bool):
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main.get_runtime_setting", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": sl_ok, "order_id": "SL1", "trigger_price": 90.0, "detail": "rejected"}), \
                 patch("kotak_real_orders.place_real_target") as mock_target:
                mock_target.return_value = {"ok": True, "order_id": "T1", "target_price": 130.0}
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            row = conn.execute("SELECT * FROM real_positions WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            return dict(row), mock_target
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_entry_places_target_only_after_sl_confirmed():
    row, mock_target = _run_entry(sl_ok=True)
    mock_target.assert_called_once()
    assert row["sl_order_id"] == "SL1"
    assert row["target_order_id"] == "T1"


def test_entry_withholds_target_when_sl_placement_fails():
    row, mock_target = _run_entry(sl_ok=False)
    mock_target.assert_not_called()
    assert row["sl_order_id"] is None
    assert row["target_order_id"] is None


def _run_partial_exit(sl_ok: bool):
    _fresh_db()
    with closing(main.get_db()) as conn:
        legs = [
            {"leg": "t1", "qty": 3, "r_multiple": "1.0R", "target_price": 110.0, "status": "open"},
            {"leg": "t2", "qty": 3, "r_multiple": "1.5R", "target_price": 115.0, "status": "open"},
            {"leg": "trail", "qty": 4, "r_multiple": None, "target_price": None, "status": "open"},
        ]
        import json
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, exit_legs_json, sl_order_id, sl_trigger_price, "
            "target_order_id, target_price) VALUES "
            "('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-21', ?, 'SL0', 90.0, 'T0', 110.0)",
            (main.time.time(), json.dumps(legs)),
        )
        conn.commit()

        with patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": sl_ok, "order_id": "SL1", "trigger_price": 90.0, "detail": "rejected"}), \
             patch("kotak_real_orders.place_real_target") as mock_target, \
             patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": True, "qty": 3, "fill_price": 110.0, "order_id": "S1",
                                 "fill_price_confirmed": True}):
            mock_target.return_value = {"ok": True, "order_id": "T2", "target_price": 115.0}
            main._maybe_place_real_partial_exit(conn, "TESTSTOCK.NS", {"leg": "t1", "qty": 3})
        row = conn.execute("SELECT * FROM real_positions WHERE symbol = 'TESTSTOCK.NS'").fetchone()
        return dict(row), mock_target


def test_staged_leg_advance_places_target_only_after_sl_confirmed():
    row, mock_target = _run_partial_exit(sl_ok=True)
    mock_target.assert_called_once()
    call_args = mock_target.call_args
    assert call_args[0][1] == 3  # next leg's own qty (t2), not the full remaining qty
    assert row["sl_order_id"] == "SL1"
    assert row["target_order_id"] == "T2"


def test_staged_leg_advance_withholds_new_target_when_sl_placement_fails():
    row, mock_target = _run_partial_exit(sl_ok=False)
    mock_target.assert_not_called()
    assert row["sl_order_id"] is None
    assert row["target_order_id"] is None
