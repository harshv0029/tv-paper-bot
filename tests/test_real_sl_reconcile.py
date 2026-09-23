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


# ---- T1/T2T infinite-retry-loop fix (2026-09-23, live SUZLON.NS finding) ---
# A resting SL for a T1/T2T-restricted symbol is ALWAYS accepted at
# placement (Kotak only enforces same-day-sell at trigger time), so the
# OLD code path here would "succeed" every retry and clear the degraded
# clock every cycle - meaning the position was genuinely unprotected the
# whole time but the 60s emergency-exit escalation could never accumulate
# enough elapsed time to fire. These tests pin the fix: once a symbol is
# confirmed T1/T2T-restricted, no further doomed SL placement is
# attempted, and the degraded clock is left running untouched.

def test_real_sl_rejection_detail_combines_rejrsn_and_rejlongdesc():
    with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED):
        detail = main._real_sl_rejection_detail("260922000149358")
    assert "T1 holdings" in detail
    assert "Trade-to-Trade stocks on the same day" in detail


def test_real_sl_rejection_detail_none_on_failure():
    with patch("kotak_neo.order_report", side_effect=Exception("network hiccup")):
        assert main._real_sl_rejection_detail("X") is None


def test_dead_sl_with_t1_t2t_rejection_flags_symbol_and_skips_replacement():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED), \
             patch("kotak_real_orders.place_real_stop_loss") as mock_place, \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
            mock_place.assert_not_called()  # no doomed placement attempted
            mock_force_exit.assert_not_called()  # not yet - degraded clock just started
        assert main._is_t1_restricted(conn, "ASHOKLEY.NS") is True
        row = conn.execute(
            "SELECT sl_order_id, protection_degraded_since FROM real_positions WHERE symbol='ASHOKLEY.NS'"
        ).fetchone()
        assert row["sl_order_id"] is None
        assert row["protection_degraded_since"] is not None


def test_degraded_clock_survives_repeated_ticks_once_t1_restricted():
    # The actual infinite-loop bug this fixes: across MULTIPLE consecutive
    # calls (simulating repeated scheduler ticks), the clock must not
    # reset - it must accumulate real elapsed time toward the escalation
    # timeout, since a T1/T2T-restricted symbol will never get a genuinely
    # live SL no matter how many times it's retried.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_real_position(conn, sl_order_id="SL-OLD", sl_trigger_price=97.0)
        with patch("kotak_neo.order_report", return_value=_LIVE_TARGET_REJECTED), \
             patch("kotak_real_orders.place_real_stop_loss") as mock_place:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")  # tick 1: detects dead, flags, starts clock
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
