"""Tests for active SL reconciliation against Kotak's own order book
(2026-09-22, live finding: ASHOKLEY.NS). A resting SL-TRG order's
placement response only ever proves Kotak ACCEPTED the conditional
order, never that a future trigger-time sell will succeed - confirmed
live the same day: a plain LIMIT sell (the profit target, order
260922000149358) for this exact symbol was rejected immediately with
ordSt "rejected" (T1/T2T same-day-sell restriction), while the SL-TRG
order (260922000149135, same symbol/shares) sat at ordSt "trigger
pending" with no rejection at all - a price-type "SL" order is accepted
to rest WITHOUT this same-day-sell check, but is not exempt from it once
it actually fires. _maybe_sync_real_stop_loss used to trust its own
local sl_order_id column as proof of live protection forever, with no
active reconciliation against Kotak's own order book to catch a SL that
goes dead silently at trigger time. See _real_sl_order_is_live's own
docstring for the full finding.

Run: pytest tests/test_real_sl_reconcile.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

# Real, live-confirmed order_report response shapes (2026-09-22,
# ASHOKLEY.NS) - trimmed to the fields _real_sl_order_is_live actually
# reads, not the full raw payload.
_LIVE_SL_TRIGGER_PENDING = {
    "stat": "Ok",
    "data": [{"nOrdNo": "260922000149135", "ordSt": "trigger pending", "rejRsn": "--"}],
    "stCode": 200,
}
_LIVE_TARGET_REJECTED = {
    "stat": "Ok",
    "data": [{
        "nOrdNo": "260922000149358", "ordSt": "rejected",
        "rejRsn": "RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,No Holdings Present "
                  " for entity account-XUAEZ across exchange across segment across product ",
        "rejLongDesc": "You don't have sufficient holdings for this stock. ... Selling "
                        "Trade-to-Trade stocks on the same day of purchase is not allowed.",
    }],
    "stCode": 200,
}
# A REJECTED order for a reason that is NOT T1/T2T (e.g. a transient RMS
# margin hiccup) - used to confirm the ordinary "dead SL gets a fresh one
# placed the same tick" retry behavior still holds for non-T1/T2T causes,
# distinct from the T1/T2T-specific infinite-loop fix below.
_LIVE_REJECTED_NON_T1T2T = {
    "stat": "Ok",
    "data": [{
        "nOrdNo": "260923000999999", "ordSt": "rejected",
        "rejRsn": "RMS:Rule: Insufficient margin", "rejLongDesc": "Margin shortfall for this order.",
    }],
    "stCode": 200,
}


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- _real_sl_order_is_live: pure classification ---------------------------

def test_real_sl_order_is_live_true_for_a_genuinely_resting_trigger():
    with patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING):
        assert main._real_sl_order_is_live("260922000149135") is True


def test_real_sl_order_is_live_false_for_a_rejected_order():
    with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED):
        assert main._real_sl_order_is_live("260922000149358") is False


def test_real_sl_order_is_live_none_when_the_read_itself_fails():
    with patch("kotak_neo.order_report", side_effect=Exception("network hiccup")):
        assert main._real_sl_order_is_live("X") is None


def test_real_sl_order_is_live_none_on_unparseable_response():
    with patch("kotak_neo.order_report", return_value={"stat": "Ok", "data": []}):
        assert main._real_sl_order_is_live("X") is None
    with patch("kotak_neo.order_report", return_value={"error": ["bad token"]}):
        assert main._real_sl_order_is_live("X") is None


def test_real_sl_order_is_live_false_for_an_unrecognized_status():
    # Fail toward re-placing/escalating, never toward silently trusting a
    # status this app has never actually seen - an allowlist, not a
    # blocklist.
    with patch("kotak_neo.order_report", return_value={"data": [{"ordSt": "some new Kotak status"}]}):
        assert main._real_sl_order_is_live("X") is False


# ---- _maybe_sync_real_stop_loss: reconciliation wired in -------------------

def _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0):
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price) VALUES "
        "('ASHOKLEY.NS', 'ASHOKLEY-EQ', 2, 162.64, 'E1', ?, ?, ?, ?)",
        (main.time.time(), main.ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price),
    )
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
        "('ASHOKLEY.NS', ?, 'long', 162.64, 97.0, 97.0, 163.35, 2, ?, 1.0, '5m')",
        (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
    )
    conn.commit()


def test_dead_sl_is_detected_and_a_fresh_one_placed_in_the_same_tick():
    # The core fix: a resting SL found dead on reconcile for a NON-T1/T2T
    # reason must not just start the degraded clock and wait - it must
    # feed the SAME tick's existing retry path immediately
    # (sl_trigger_price cleared too, not just sl_order_id, so the "no
    # upward move" gate doesn't skip it).
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_REJECTED_NON_T1T2T), \
             patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 97.0}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_force_exit.assert_not_called()
        events = conn.execute(
            "SELECT leg, event FROM real_order_events WHERE symbol = 'ASHOKLEY.NS' ORDER BY id"
        ).fetchall()
        assert ("sl", "found_dead_on_reconcile") in [(e["leg"], e["event"]) for e in events]
        row = conn.execute(
            "SELECT sl_order_id, protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
        ).fetchone()
        # A fresh SL landed in this SAME call, not just the degraded clock
        # starting and waiting for a future price move.
        assert row["sl_order_id"] == "SL-NEW"
        assert row["protection_degraded_since"] is None  # cleared once the fresh SL confirmed
        assert main._is_t1_restricted(conn, "ASHOKLEY.NS") is False


# ---- T1/T2T flagging correction (2026-09-23, live SUZLON.NS finding) -------
# First cut of this fix (same day) called _flag_if_t1_restricted from this
# reconcile path whenever a dead SL's rejection detail carried the T1/T2T
# marker text - WRONG, per the exact precedent already documented above
# _maybe_place_real_entry's own target-placement-failure branch
# (2026-09-22, IDEA.NS/ASHOKLEY.NS/CONCOR.NS): a rejection here can
# equally be caused by a competing resting order or by asking to sell
# more than is currently held (see _reconcile_real_qty below), neither of
# which is genuine same-day-sale restriction. These tests pin the
# CORRECTED behavior: detail is logged for visibility, never fed to the
# permanent-blacklist flag from this call site.

def test_real_sl_rejection_detail_combines_rejrsn_and_rejlongdesc():
    with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED):
        detail = main._real_sl_rejection_detail("260922000149358")
    assert "T1 holdings" in detail
    assert "Trade-to-Trade stocks on the same day" in detail


def test_real_sl_rejection_detail_none_on_failure():
    with patch("kotak_neo.order_report", side_effect=Exception("network hiccup")):
        assert main._real_sl_rejection_detail("X") is None


def test_dead_sl_with_t1_t2t_worded_rejection_does_not_flag_the_symbol():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED), \
             patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 97.0}), \
             patch.object(main.time, "sleep", return_value=None):
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
        # T2T-worded text was present in the rejection detail, but this
        # call site must never treat that as proof - the false positive
        # this whole correction exists to prevent.
        assert main._is_t1_restricted(conn, "ASHOKLEY.NS") is False
        events = conn.execute(
            "SELECT detail FROM real_order_events WHERE symbol = 'ASHOKLEY.NS' AND event = 'found_dead_on_reconcile'"
        ).fetchone()
        assert "Trade-to-Trade stocks on the same day" in events["detail"]  # logged for visibility, not acted on


def test_degraded_clock_survives_repeated_ticks_for_a_symbol_restricted_via_a_trusted_source():
    # The actual infinite-loop bug: across MULTIPLE consecutive calls
    # (simulating repeated scheduler ticks), the clock must not reset -
    # it must accumulate real elapsed time toward the escalation timeout,
    # since a genuinely T1/T2T-restricted symbol will never get a live SL
    # no matter how many times it's retried. Restriction here comes from
    # a TRUSTED source (direct DB row, standing in for
    # _maybe_place_real_entry's own immediate-rejection flagging path,
    # still valid) - not from this reconcile path, which no longer flags.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        conn.execute(
            "INSERT OR IGNORE INTO real_t1_restricted (symbol, day, flagged_at, detail) "
            "VALUES ('ASHOKLEY.NS', ?, ?, 'Selling Trade-to-Trade stocks on the same day of purchase is not allowed.')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()
        with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED), \
             patch("kotak_real_orders.place_real_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")  # tick 1: detects dead, starts clock
            first = conn.execute(
                "SELECT protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
            ).fetchone()["protection_degraded_since"]
            assert first is not None

            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")  # tick 2: still restricted, already NULL sl_order_id
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")  # tick 3: same
            mock_place.assert_not_called()  # never re-attempted across any of the 3 ticks
            second = conn.execute(
                "SELECT protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
            ).fetchone()["protection_degraded_since"]
            assert second == first  # untouched across ticks - this is the bug fix


# ---- Qty reconciliation (2026-09-23, live SUZLON.NS finding) ---------------
# SUZLON.NS's real qty went 3->2 via an organic fill (a resting order
# filled directly at Kotak, no corresponding call into this app's own
# partial-exit mirror), but real_positions.qty never got corrected - every
# subsequent SL placement kept sizing for 3 against a holding that only
# had 2.

_KOTAK_POSITIONS_HOLDS_2 = {
    "data": [{"trdSym": "ASHOKLEY-EQ", "exSeg": "nse_cm", "flBuyQty": "3", "flSellQty": "1"}]
}
_KOTAK_POSITIONS_HOLDS_3 = {
    "data": [{"trdSym": "ASHOKLEY-EQ", "exSeg": "nse_cm", "flBuyQty": "3", "flSellQty": "0"}]
}
_KOTAK_POSITIONS_FLAT = {
    "data": [{"trdSym": "ASHOKLEY-EQ", "exSeg": "nse_cm", "flBuyQty": "3", "flSellQty": "3"}]
}


def test_real_held_qty_computes_net_of_fills():
    with patch("kotak_neo.positions", return_value=_KOTAK_POSITIONS_HOLDS_2):
        assert main._real_held_qty("ASHOKLEY-EQ") == 2.0


def test_real_held_qty_none_on_failure():
    with patch("kotak_neo.positions", side_effect=Exception("network hiccup")):
        assert main._real_held_qty("ASHOKLEY-EQ") is None


def test_reconcile_real_qty_corrects_a_stale_tracked_quantity():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol='ASHOKLEY.NS'").fetchone()
        assert real_row["qty"] == 2  # fixture default
        with patch("kotak_neo.positions", return_value=_KOTAK_POSITIONS_HOLDS_3):
            corrected = main._reconcile_real_qty(conn, real_row)
        assert corrected["qty"] == 3
        row = conn.execute("SELECT qty FROM real_positions WHERE symbol='ASHOKLEY.NS'").fetchone()
        assert row["qty"] == 3


def test_reconcile_real_qty_leaves_matching_quantity_untouched():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol='ASHOKLEY.NS'").fetchone()
        with patch("kotak_neo.positions", return_value=_KOTAK_POSITIONS_HOLDS_2):  # matches the fixture's qty=2
            corrected = main._reconcile_real_qty(conn, real_row)
        assert corrected["qty"] == 2


def test_reconcile_real_qty_fails_quiet_on_unreadable_check():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol='ASHOKLEY.NS'").fetchone()
        with patch("kotak_neo.positions", side_effect=Exception("network hiccup")):
            corrected = main._reconcile_real_qty(conn, real_row)
        assert corrected["qty"] == 2  # unchanged, never forced to 0 or guessed


def test_sync_stop_loss_sizes_the_fresh_sl_off_the_corrected_qty():
    # End-to-end: a stale local qty (3) is corrected to what Kotak
    # actually holds (2) BEFORE the fresh SL placement, so the SL that
    # actually gets sent is sized 2, not 3 - the exact live SUZLON.NS bug.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        conn.execute("UPDATE real_positions SET qty = 3 WHERE symbol = 'ASHOKLEY.NS'")
        conn.commit()
        with patch("kotak_neo.positions", return_value=_KOTAK_POSITIONS_HOLDS_2), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL-NEW", "trigger_price": 98.0}) as mock_place:
            conn.execute("UPDATE signal_state SET stop_loss = 98.0 WHERE symbol = 'ASHOKLEY.NS'")
            conn.commit()
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_place.assert_called_once_with("ASHOKLEY-EQ", 2.0, 98.0)


def test_t1_restricted_symbol_escalates_to_forced_exit_once_timeout_exceeded():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id=None, sl_trigger_price=None)
        conn.execute(
            "UPDATE real_positions SET protection_degraded_since = ? WHERE symbol = 'ASHOKLEY.NS'",
            (main.time.time() - 9999,),  # far past any capital tier's timeout
        )
        conn.execute(
            "INSERT OR IGNORE INTO real_t1_restricted (symbol, day, flagged_at, detail) "
            "VALUES ('ASHOKLEY.NS', ?, ?, 'Selling Trade-to-Trade stocks on the same day of purchase is not allowed.')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()
        with patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_force_exit.assert_called_once_with(conn, "ASHOKLEY.NS")


def test_dead_sl_with_no_replacement_available_starts_the_degraded_clock_not_a_forced_exit():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED), \
             patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": False, "detail": "still T2T"}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_force_exit.assert_not_called()  # never on the first detection - same non-escalation guarantee
        row = conn.execute(
            "SELECT sl_order_id, protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
        ).fetchone()
        assert row["sl_order_id"] is None
        assert row["protection_degraded_since"] is not None


def test_a_genuinely_live_sl_is_left_untouched_no_wasted_cancel_replace():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-LIVE", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_SL_TRIGGER_PENDING), \
             patch("kotak_real_orders.cancel_real_order") as mock_cancel, \
             patch("kotak_real_orders.place_real_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_cancel.assert_not_called()
            mock_place.assert_not_called()
        row = conn.execute("SELECT sl_order_id FROM real_positions WHERE symbol='ASHOKLEY.NS'").fetchone()
        assert row["sl_order_id"] == "SL-LIVE"  # untouched


def test_an_unreadable_reconcile_check_leaves_existing_state_untouched():
    # Fail-quiet on unknown, never force an exit or clear a possibly-still-
    # good order id on a mere API hiccup - same "unknown -> refuse, don't
    # force" stance as _real_loss_budget elsewhere in this file.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-LIVE", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", side_effect=Exception("network hiccup")), \
             patch("kotak_real_orders.cancel_real_order") as mock_cancel, \
             patch("kotak_real_orders.place_real_stop_loss") as mock_place, \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_cancel.assert_not_called()
            mock_place.assert_not_called()
            mock_force_exit.assert_not_called()
        row = conn.execute(
            "SELECT sl_order_id, protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
        ).fetchone()
        assert row["sl_order_id"] == "SL-LIVE"
        assert row["protection_degraded_since"] is None
