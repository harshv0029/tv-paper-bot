"""Tests for _maybe_sync_real_stop_loss_short (2026-09-30, explicit user
instruction: "make short positions equally mirrored as done in buy
positions") - the per-TICK (every ~30s) trailing-stop/retry/degraded-
protection engine for a real short position, bringing it to full parity
with the long side's _maybe_sync_real_stop_loss (in place since
2026-09-08/09-10/09-22/09-23). Before this, a short's ONLY self-heal
mechanism was the 5-min reconcile pass (see test_short_position_auto_heal.py)
- this closes the remaining gap the user explicitly flagged.

Every behavior mirrored here is the long side's own, direction-flipped:
a short's stop trails DOWN (toward entry), its protective order is a
resting BUY, and emergency escalation covers (buys) rather than sells.

Run: pytest tests/test_short_stop_loss_tick_sync.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

_LIVE_SL_TRIGGER_PENDING = {
    "stat": "Ok", "data": [{"nOrdNo": "SL-OLD", "ordSt": "trigger pending", "rejRsn": "--"}], "stCode": 200,
}
_LIVE_REJECTED_NON_T1T2T = {
    "stat": "Ok",
    "data": [{"nOrdNo": "SL-OLD", "ordSt": "rejected",
              "rejRsn": "RMS:Rule: Insufficient margin", "rejLongDesc": "Margin shortfall."}],
    "stCode": 200,
}
_LIVE_REJECTED_T1T2T = {
    "stat": "Ok",
    "data": [{"nOrdNo": "SL-OLD", "ordSt": "rejected",
              "rejRsn": "RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,No Holdings Present ",
              "rejLongDesc": "Selling Trade-to-Trade stocks on the same day of purchase is not allowed."}],
    "stCode": 200,
}


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _insert_open_real_short(conn, symbol="TCS.NS", entry_price=2100.0, qty=1,
                             sl_order_id=None, sl_trigger_price=None, stop_loss=2100.0):
    conn.execute(
        "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) VALUES "
        "(?, ?, ?, ?, 'E1', ?, ?, ?, ?, 'range_short')",
        (symbol, symbol.replace(".NS", "-EQ"), qty, entry_price,
         main.time.time(), main.ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price),
    )
    conn.execute(
        "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
        "(?, ?, 'short', ?, ?, ?, ?, ?, ?, 1.0, '5m')",
        (symbol, main.ist_now().strftime("%Y-%m-%d"), entry_price, stop_loss, entry_price * 1.02,
         entry_price * 0.9, qty, main.time.time()),
    )
    conn.commit()


def _still_open_short():
    return {"data": [{"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "1"}]}


def test_no_op_when_no_real_short_position_exists():
    _fresh_db()
    with closing(main.get_db()) as conn:
        # Must not raise, must not touch anything.
        main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")


def test_places_a_fresh_sl_when_none_is_resting_yet():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id=None, sl_trigger_price=None, stop_loss=2142.0)
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value={"data": []}), \
             patch("kotak_real_orders.cancel_existing_resting_sl_short", return_value={"cancelled": [], "detail": None}), \
             patch("kotak_real_orders.place_real_short_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 2142.0}):
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        assert row["sl_order_id"] == "SL-NEW"
        assert row["sl_trigger_price"] == 2142.0
        assert row["protection_degraded_since"] is None


def test_no_op_when_the_paper_stop_has_not_moved_favorably():
    # A short's stop only trails DOWN - a new_stop that is HIGHER than (or
    # equal to) the current resting trigger is not a favorable move and
    # must not trigger a cancel/replace.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id="SL-OLD", sl_trigger_price=2100.0, stop_loss=2100.0)
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING), \
             patch("kotak_real_orders.cancel_real_order") as mock_cancel, \
             patch("kotak_real_orders.place_real_short_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        mock_cancel.assert_not_called()
        mock_place.assert_not_called()


def test_replaces_when_the_paper_stop_has_trailed_down_favorably():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id="SL-OLD", sl_trigger_price=2100.0, stop_loss=2080.0)
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("kotak_real_orders.place_real_short_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 2080.0}):
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        assert row["sl_order_id"] == "SL-NEW"
        assert row["sl_trigger_price"] == 2080.0


def test_dead_sl_is_detected_and_a_fresh_one_placed_in_the_same_tick():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id="SL-OLD", sl_trigger_price=2100.0, stop_loss=2100.0)
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value=_LIVE_REJECTED_NON_T1T2T), \
             patch("kotak_real_orders.cancel_existing_resting_sl_short", return_value={"cancelled": [], "detail": None}), \
             patch("kotak_real_orders.place_real_short_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 2100.0}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_short_exit") as mock_cover:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
            mock_cover.assert_not_called()
        events = conn.execute(
            "SELECT leg, event FROM real_order_events WHERE symbol = 'TCS.NS' ORDER BY id"
        ).fetchall()
        assert ("sl", "found_dead_on_reconcile") in [(e["leg"], e["event"]) for e in events]
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        assert row["sl_order_id"] == "SL-NEW"
        assert row["protection_degraded_since"] is None


def test_t1_restricted_symbol_does_not_attempt_placement_and_marks_degraded():
    # A symbol already flagged T1/T2T-restricted by an EARLIER tick's
    # failed placement attempt (main._flag_if_t1_restricted, reused as-is
    # for shorts - it's symbol-keyed, not direction-specific) must not
    # have a fresh SL attempted again this tick - it's a known-doomed
    # placement, per the long side's own T1/T2T infinite-retry-loop fix.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id="SL-OLD", sl_trigger_price=2100.0, stop_loss=2080.0)
        main._flag_if_t1_restricted(conn, "TCS.NS", _LIVE_REJECTED_T1T2T["data"][0]["rejLongDesc"])
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING), \
             patch("kotak_real_orders.place_real_short_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        mock_place.assert_not_called()
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        assert row["protection_degraded_since"] is not None
        assert main._is_t1_restricted(conn, "TCS.NS") is True


def test_degraded_timeout_exceeded_triggers_emergency_cover_not_a_sell():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id=None, sl_trigger_price=None, stop_loss=2100.0)
        conn.execute(
            "UPDATE real_positions_short SET protection_degraded_since = ? WHERE symbol = 'TCS.NS'",
            (main.time.time() - 9999,),
        )
        conn.commit()
        with patch("main.get_scheduler_capital_inr", return_value=100000.0), \
             patch.object(main, "_maybe_place_real_short_exit") as mock_cover, \
             patch.object(main, "_maybe_place_real_exit") as mock_sell:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        mock_cover.assert_called_once_with(conn, "TCS.NS")
        mock_sell.assert_not_called()


def test_exit_in_flight_race_skips_placement_when_kotak_shows_no_open_short():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id=None, sl_trigger_price=None, stop_loss=2100.0)
        with patch("kotak_neo.positions", return_value={"data": []}), \
             patch("kotak_real_orders.place_real_short_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        mock_place.assert_not_called()


def test_cas_transition_rejection_escalates_to_emergency_cover():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, sl_order_id=None, sl_trigger_price=None, stop_loss=2100.0)
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_real_orders.cancel_existing_resting_sl_short", return_value={"cancelled": [], "detail": None}), \
             patch("kotak_real_orders.place_real_short_stop_loss",
                   return_value={"ok": False, "detail": "OMS: Trading session is in Transition to CAS session"}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_short_exit") as mock_cover:
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        mock_cover.assert_called_once_with(conn, "TCS.NS")


def test_self_heals_a_missing_signal_state_short_row():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) VALUES "
            "('TCS.NS', 'TCS-EQ', 1, 2100.0, 'E1', ?, ?, NULL, NULL, 'range_short')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
        with patch("kotak_neo.positions", return_value=_still_open_short()), \
             patch("kotak_neo.order_report", return_value={"data": []}), \
             patch("kotak_real_orders.cancel_existing_resting_sl_short", return_value={"cancelled": [], "detail": None}), \
             patch("kotak_real_orders.place_real_short_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 2142.0}):
            main._maybe_sync_real_stop_loss_short(conn, "TCS.NS")
        row = conn.execute(
            "SELECT * FROM signal_state_short WHERE symbol = 'TCS.NS' AND status = 'short'"
        ).fetchone()
        assert row is not None


# ---- small helpers built alongside the engine above -------------------------

def test_real_held_qty_short_computes_net_of_fills():
    fake_positions = {"data": [
        {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "1", "flSellQty": "3"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        assert main._real_held_qty_short("TCS-EQ") == 2.0


def test_real_held_qty_short_none_on_failure():
    with patch("kotak_neo.positions", side_effect=Exception("down")):
        assert main._real_held_qty_short("TCS-EQ") is None


def test_reconcile_real_qty_short_corrects_a_stale_tracked_quantity():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, qty=3)
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        with patch("kotak_neo.positions", return_value={"data": [
            {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "2"},
        ]}):
            corrected = main._reconcile_real_qty_short(conn, real_row)
        assert corrected["qty"] == 2.0
        row = conn.execute("SELECT qty FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        assert row["qty"] == 2.0


def test_reconcile_real_qty_short_leaves_matching_quantity_untouched():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, qty=1)
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        with patch("kotak_neo.positions", return_value={"data": [
            {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "1"},
        ]}):
            corrected = main._reconcile_real_qty_short(conn, real_row)
        assert corrected["qty"] == 1


def test_reconcile_real_qty_short_fails_quiet_on_unreadable_check():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_short(conn, qty=1)
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'TCS.NS'").fetchone()
        with patch("kotak_neo.positions", side_effect=Exception("down")):
            corrected = main._reconcile_real_qty_short(conn, real_row)
        assert corrected["qty"] == 1


def test_place_real_stop_loss_with_retry_short_retries_then_succeeds():
    calls = {"n": 0}

    def fake_place(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return {"ok": False, "detail": "transient"}
        return {"ok": True, "order_id": "SL-1", "trigger_price": 2100.0}

    with patch("kotak_real_orders.place_real_short_stop_loss", side_effect=fake_place), \
         patch.object(main.time, "sleep", return_value=None):
        result = main._place_real_stop_loss_with_retry_short("TCS-EQ", 1, 2100.0, attempts=3)
    assert result["ok"] is True
    assert calls["n"] == 2
