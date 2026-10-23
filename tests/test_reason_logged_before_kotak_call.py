"""B-1350 (2026-10-23, NATIONALUM): a Kotak SL cancel + SELL reached the broker
with no app reason row. Every path that cancels or sells must write its reason
row BEFORE calling Kotak, so a lost post-call log can never hide why.

Run: pytest tests/test_reason_logged_before_kotak_call.py -v
"""
from contextlib import closing
from unittest.mock import patch

import main
from tests.test_cas_transition_market_exit import _fresh_db, _insert_open_real_position


def _event_rows(conn):
    return conn.execute("SELECT leg, event FROM real_order_events WHERE symbol = 'TESTSTOCK.NS'").fetchall()


def test_sl_sync_logs_move_intent_before_cancel():
    _fresh_db()
    seen = {}
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=90.0)

        def _cancel(order_id):
            seen["rows"] = [tuple(r) for r in _event_rows(conn)]
            return {"ok": True}

        with patch("main._real_sl_order_is_live", return_value=True), \
             patch("kotak_real_orders.cancel_real_order", side_effect=_cancel), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 92.0}):
            main._maybe_sync_real_stop_loss(conn, "TESTSTOCK.NS")
    assert ("sl", "move_intent") in seen["rows"]


def test_partial_exit_logs_intent_before_cancel():
    _fresh_db()
    seen = {}
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=90.0)
        legs = [{"leg": "T1", "qty": 1, "target_price": 110.0, "status": "open"},
                {"leg": "trail", "qty": 1, "target_price": None, "status": "open"}]
        conn.execute("UPDATE real_positions SET exit_legs_json = ? WHERE symbol = 'TESTSTOCK.NS'",
                     (main.json.dumps(legs),))
        conn.commit()

        def _cancel(order_id):
            seen.setdefault("rows", [tuple(r) for r in _event_rows(conn)])
            return {"ok": True}

        with patch("kotak_real_orders.cancel_real_order", side_effect=_cancel), \
             patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": True, "order_id": "X1", "qty": 1, "fill_price": 110.0,
                                 "fill_price_confirmed": True}), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 92.0}), \
             patch("kotak_real_orders.place_real_target", return_value={"ok": False, "detail": "x"}), \
             patch("kotak_real_orders.cancel_existing_resting_target", return_value={"ok": True}):
            main._maybe_place_real_partial_exit(conn, "TESTSTOCK.NS", {"leg": "T1"})
    assert ("staged_T1", "intent") in seen["rows"]
