"""Tests for the 2026-09-23 user instruction: "In each of scorecard add a
logic of placing why you buy only x qty when a buy order is placed each
time" - main._describe_real_qty_sizing explains, in plain English, which
of the three inputs to qty = min(paper_qty, max_by_cap, max_by_capital)
(see main._maybe_place_real_entry) actually bound the final REAL order
qty, and _maybe_place_real_entry now writes that explanation into the
confirmed real_trades row's own `detail` field (previously always None on
a clean fill) so it reaches the Kotak Order Ledger via /kotak-neo/real-trades
without any separate lookup.

Run: pytest tests/test_real_qty_sizing_reason.py -v
"""
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


def _enable_real_trading(conn):
    conn.execute(
        "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
        "VALUES (1, 1, ?, 'test', 'test')", (main.time.time(),),
    )
    conn.commit()


def _insert_paper_signal(conn, symbol, qty, stop_loss=90.0, target=130.0):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
        "VALUES (?, '2026-09-23', 'long', 100.0, ?, ?, ?, ?, ?, 1.0, '5m')",
        (symbol, stop_loss, stop_loss, target, qty, main.time.time()),
    )
    conn.commit()


# ---- _describe_real_qty_sizing: pure text logic ----------------------------

def test_full_paper_size_when_nothing_binds():
    msg = main._describe_real_qty_sizing(paper_qty=3, max_by_cap=10, max_by_capital=20, qty=3)
    assert msg == ("sized to the paper signal's own qty (3) - remaining daily cap "
                    "and real account capital both had room for at least that many")


def test_capped_by_daily_cap_only():
    msg = main._describe_real_qty_sizing(paper_qty=5, max_by_cap=1, max_by_capital=20, qty=1)
    assert msg == "paper signal called for 5, capped to 1 by remaining daily cap (room for 1)"


def test_capped_by_real_capital_only():
    msg = main._describe_real_qty_sizing(paper_qty=5, max_by_cap=20, max_by_capital=2, qty=2)
    assert msg == "paper signal called for 5, capped to 2 by real account capital (room for 2)"


def test_capped_by_both_when_tied():
    msg = main._describe_real_qty_sizing(paper_qty=5, max_by_cap=2, max_by_capital=2, qty=2)
    assert "remaining daily cap (room for 2)" in msg
    assert "real account capital (room for 2)" in msg
    assert msg.startswith("paper signal called for 5, capped to 2 by")


def test_tie_with_paper_qty_reads_as_full_size():
    # qty happens to equal paper_qty even though max_by_capital was also
    # exactly qty - real money still had room for the full paper size, so
    # this isn't really a "cap", it's a coincidental tie.
    msg = main._describe_real_qty_sizing(paper_qty=1, max_by_cap=5, max_by_capital=1, qty=1)
    assert msg.startswith("sized to the paper signal's own qty (1)")


# ---- _maybe_place_real_entry: the reason lands in real_trades.detail -------

def test_confirmed_entry_logs_full_paper_size_reason():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS", qty=2)
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 2, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target", return_value={"ok": True, "order_id": "T1", "target_price": 130.0}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            row = conn.execute(
                "SELECT detail FROM real_trades WHERE symbol='TESTSTOCK.NS' AND status='confirmed'"
            ).fetchone()
            assert row is not None
            # paper_qty comes back from SQLite as a float (2.0), same
            # formatting the pre-existing skip-path detail messages
            # already use (e.g. "paper qty 2.0, 1 share = Rs...").
            assert row["detail"].startswith("sized to the paper signal's own qty (2.0)")
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_confirmed_entry_logs_daily_cap_capped_reason():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS", qty=3)
            # capital is huge (never binds); today's spend leaves only
            # Rs100 of daily cap headroom at ltp=100 -> max_by_cap=1 <
            # paper_qty=3, so qty is capped to 1 by the daily cap alone.
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=999900.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 1, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target", return_value={"ok": True, "order_id": "T1", "target_price": 130.0}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            row = conn.execute(
                "SELECT detail FROM real_trades WHERE symbol='TESTSTOCK.NS' AND status='confirmed'"
            ).fetchone()
            assert row is not None
            assert row["detail"] == "paper signal called for 3.0, capped to 1 by remaining daily cap (room for 1)"
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_unconfirmed_fill_appends_note_after_reason():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS", qty=1)
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 1, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": False}), \
                 patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target", return_value={"ok": True, "order_id": "T1", "target_price": 130.0}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            row = conn.execute(
                "SELECT detail FROM real_trades WHERE symbol='TESTSTOCK.NS' AND status='confirmed'"
            ).fetchone()
            assert row["detail"].startswith("sized to the paper signal's own qty (1.0)")
            assert row["detail"].endswith(
                "; fill not yet confirmed by Kotak - using requested qty/estimated LTP"
            )
    finally:
        del os.environ["REAL_TRADING_ENABLED"]
