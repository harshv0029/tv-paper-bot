"""Tests for the 2026-09-22 CAS-transition fix, explicit user instruction:
"if reason is CSA THEN place market price order request" - live finding
WAAREEENER.NS/NATIONALUM.NS, both stuck near EOD when every SL/target
retry (and even a manual MARKET sell) got rejected with "OMS: Trading
session is in Transition to CAS session" until a human intervened
manually. See kotak_real_orders.is_cas_transition_rejection's own
docstring for the full live evidence and why the fix is "escalate
straight to a market exit attempt" rather than "retry with a different
order type and expect it to land immediately."

Run: pytest tests/test_cas_transition_market_exit.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import kotak_real_orders
import main

_CAS_REJECTION_DETAIL = "OMS: Trading session is in Transition to CAS session"
_T1_REJECTION_DETAIL = (
    "RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,No Holdings Present  for entity "
    "account-XUAEZ across exchange across segment across product "
)
_TICK_SIZE_DETAIL = "16283 : Order price is not a multiple of tick size  "


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


# ---- is_cas_transition_rejection: pure classification ----------------------

def test_true_for_the_exact_live_rejection_text():
    assert kotak_real_orders.is_cas_transition_rejection(_CAS_REJECTION_DETAIL) is True


def test_true_case_insensitively():
    assert kotak_real_orders.is_cas_transition_rejection(_CAS_REJECTION_DETAIL.lower()) is True
    assert kotak_real_orders.is_cas_transition_rejection(_CAS_REJECTION_DETAIL.upper()) is True


def test_false_for_t1_rejection():
    assert kotak_real_orders.is_cas_transition_rejection(_T1_REJECTION_DETAIL) is False


def test_false_for_tick_size_rejection():
    assert kotak_real_orders.is_cas_transition_rejection(_TICK_SIZE_DETAIL) is False


def test_false_for_none_or_empty():
    assert kotak_real_orders.is_cas_transition_rejection(None) is False
    assert kotak_real_orders.is_cas_transition_rejection("") is False


# ---- _maybe_place_real_entry: escalates on CAS, not on other rejections ----

def _insert_paper_signal(conn, symbol, qty=1, stop_loss=90.0, target=130.0):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
        "VALUES (?, '2026-09-22', 'long', 100.0, ?, ?, ?, ?, ?, 1.0, '5m')",
        (symbol, stop_loss, stop_loss, target, qty, main.time.time()),
    )
    conn.commit()


def test_entry_sl_rejected_with_cas_reason_escalates_to_market_exit():
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
                       return_value={"ok": True, "qty": 1, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": False, "detail": _CAS_REJECTION_DETAIL}), \
                 patch.object(main, "_maybe_place_real_exit") as mock_exit:
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
                mock_exit.assert_called_once_with(conn, "TESTSTOCK.NS")
            row = conn.execute("SELECT protection_degraded_since FROM real_positions WHERE symbol='TESTSTOCK.NS'").fetchone()
            # Escalated immediately - never started the ordinary degraded clock.
            assert row["protection_degraded_since"] is None
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_entry_sl_rejected_with_t1_reason_does_not_escalate():
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
                       return_value={"ok": True, "qty": 1, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": False, "detail": _T1_REJECTION_DETAIL}), \
                 patch.object(main, "_maybe_place_real_exit") as mock_exit:
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
                mock_exit.assert_not_called()
            row = conn.execute("SELECT protection_degraded_since FROM real_positions WHERE symbol='TESTSTOCK.NS'").fetchone()
            # Ordinary degraded clock started instead - the pre-existing, correct behavior.
            assert row["protection_degraded_since"] is not None
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


# ---- _maybe_sync_real_stop_loss: escalates on CAS, not on other rejections -

def _insert_open_real_position(conn, sl_order_id=None, sl_trigger_price=None):
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price) VALUES "
        "('TESTSTOCK.NS', 'TESTSTOCK-EQ', 2, 100.0, 'E1', ?, ?, ?, ?)",
        (main.time.time(), main.ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price),
    )
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
        "('TESTSTOCK.NS', ?, 'long', 100.0, 92.0, 90.0, 130.0, 2, ?, 1.0, '5m')",
        (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
    )
    conn.commit()


def test_sync_sl_replacement_rejected_with_cas_reason_escalates_to_market_exit():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=90.0)
        with patch("main._real_sl_order_is_live", return_value=True), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": False, "detail": _CAS_REJECTION_DETAIL}), \
             patch.object(main, "_maybe_place_real_exit") as mock_exit:
            main._maybe_sync_real_stop_loss(conn, "TESTSTOCK.NS")
            mock_exit.assert_called_once_with(conn, "TESTSTOCK.NS")


def test_sync_sl_replacement_rejected_with_t1_reason_does_not_escalate():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=90.0)
        with patch("main._real_sl_order_is_live", return_value=True), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": False, "detail": _T1_REJECTION_DETAIL}), \
             patch.object(main, "_maybe_place_real_exit") as mock_exit:
            main._maybe_sync_real_stop_loss(conn, "TESTSTOCK.NS")
            mock_exit.assert_not_called()
        row = conn.execute(
            "SELECT protection_degraded_since FROM real_positions WHERE symbol='TESTSTOCK.NS'"
        ).fetchone()
        assert row["protection_degraded_since"] is not None
