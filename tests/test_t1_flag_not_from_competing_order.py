"""Tests for the 2026-09-22 correction: a target-order rejection must NOT
permanently T1/T2T-blacklist the symbol when it happens while a resting
SL is the known competing order (sl_confirmed True) - only when there is
no such explanation available.

Root cause (confirmed via live evidence + broker documentation research,
see main.py's own comments at each corrected call site): Kotak's RMS
enforces "one exit order per holding" - placing a target while an SL
already rests for the same qty is REJECTED with the T1-holdings message
regardless of whether the symbol itself is genuinely T2T-restricted. Live
evidence same day: IDEA.NS/ASHOKLEY.NS/CONCOR.NS all got this rejection
while their SL rested, then sold successfully seconds-to-minutes after
that SL was cancelled - real T+1 settlement cannot clear that fast, so
the rejection was never really about settlement timing. The original
2026-09-09 MEDICAMEQ.NS incident that started _flag_if_t1_restricted's
"permanent, structural" design was the same misdiagnosis.

Before this fix, all three tests below would have inserted a
real_t1_restricted row and permanently blocked the symbol from every
future real entry - even though the position's own resting SL was fine.

Run: pytest tests/test_t1_flag_not_from_competing_order.py -v
"""
import json
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

_T1_REJECTION_DETAIL = (
    "RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,No Holdings Present  for entity "
    "account-XUAEZ across exchange across segment across product "
)


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
        "VALUES (?, '2026-09-22', 'long', 100.0, ?, ?, ?, ?, ?, 1.0, '5m')",
        (symbol, stop_loss, stop_loss, target, qty, main.time.time()),
    )
    conn.commit()


def test_entry_flow_target_rejection_does_not_blacklist_while_sl_is_resting():
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
                       return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target",
                       return_value={"ok": False, "detail": _T1_REJECTION_DETAIL}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            row = conn.execute("SELECT * FROM real_positions WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row["sl_order_id"] == "SL1"  # the SL itself is fine, unaffected
            assert row["target_order_id"] is None  # target genuinely didn't rest
            assert main._is_t1_restricted(conn, "TESTSTOCK.NS") is False
            events = conn.execute(
                "SELECT leg, event FROM real_order_events WHERE symbol = 'TESTSTOCK.NS' ORDER BY id"
            ).fetchall()
            # Still visibly logged as a failure - just not escalated to a permanent ban.
            assert ("target", "failed") in [(e["leg"], e["event"]) for e in events]
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_staged_leg_advance_target_rejection_does_not_blacklist_while_sl_is_resting():
    _fresh_db()
    with closing(main.get_db()) as conn:
        legs = [
            {"leg": "t1", "qty": 3, "r_multiple": "1.0R", "target_price": 110.0, "status": "open"},
            {"leg": "t2", "qty": 3, "r_multiple": "1.5R", "target_price": 115.0, "status": "open"},
            {"leg": "trail", "qty": 4, "r_multiple": None, "target_price": None, "status": "open"},
        ]
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, exit_legs_json, sl_order_id, sl_trigger_price, "
            "target_order_id, target_price) VALUES "
            "('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-22', ?, 'SL0', 90.0, 'T0', 110.0)",
            (main.time.time(), json.dumps(legs)),
        )
        conn.commit()
        with patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("kotak_real_orders.cancel_existing_resting_target",
                   return_value={"cancelled": [], "detail": None}), \
             patch("main._place_real_stop_loss_with_retry",
                   return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
             patch("kotak_real_orders.place_real_target",
                   return_value={"ok": False, "detail": _T1_REJECTION_DETAIL}), \
             patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": True, "qty": 3, "fill_price": 110.0, "order_id": "S1",
                                 "fill_price_confirmed": True}):
            main._maybe_place_real_partial_exit(conn, "TESTSTOCK.NS", {"leg": "t1", "qty": 3})
        row = conn.execute("SELECT * FROM real_positions WHERE symbol = 'TESTSTOCK.NS'").fetchone()
        assert row["sl_order_id"] == "SL1"
        assert row["target_order_id"] is None
        assert main._is_t1_restricted(conn, "TESTSTOCK.NS") is False


def test_governance_backfill_no_longer_flags_its_target_rejection():
    # The governance-backfill target-placement block (inside
    # kotak_neo_reconcile_real_positions) runs after an SL is already
    # resting (either pre-existing or just placed by the SL block
    # immediately above it in the same function) - same competing-order
    # situation as the other two call sites, fixed the same way. The full
    # endpoint needs a live-account-wide reconcile setup unrelated to this
    # fix, so this confirms the actual invariant directly: no
    # _flag_if_t1_restricted call remains between the target-rejection
    # log line and the next function boundary.
    import inspect
    src = inspect.getsource(main.kotak_neo_reconcile_real_positions)
    marker = 'new_state="none (placement failed)", detail=target_result.get("detail"),\n                    )'
    assert marker in src, "governance-backfill target-failed log line moved - re-locate before trusting this check"
    after_marker = src.split(marker, 1)[1]
    next_boundary = after_marker.find("governance_backfilled.append")
    assert next_boundary != -1
    between = after_marker[:next_boundary]
    assert "_flag_if_t1_restricted(" not in between  # the call, not just a comment mentioning it


def test_a_rejection_with_no_competing_order_still_gets_permanently_flagged():
    # The correction narrows WHERE flagging happens - it does not remove
    # the mechanism. A rejection on a plain full-position exit (both legs
    # already confirmed cancelled first, so no competing order remains) is
    # still real evidence and must still result in a permanent block -
    # this is _maybe_place_real_exit's own rejection path, untouched by
    # this fix.
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES "
            "('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-22')",
            (main.time.time(),),
        )
        conn.commit()
        with patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": False, "detail": _T1_REJECTION_DETAIL}):
            main._maybe_place_real_exit(conn, "TESTSTOCK.NS")
        assert main._is_t1_restricted(conn, "TESTSTOCK.NS") is True
