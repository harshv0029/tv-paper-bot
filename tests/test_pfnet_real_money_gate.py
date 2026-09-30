"""Tests for the 2026-09-30 PFnet >= 1 real-money gate (explicit user
instruction, confirmed via AskUserQuestion after being shown the actual
consequence: "Yes - disable non-viable live strategies now"). A NEW real
position may only be opened for a strategy whose strategy_registry.py
metrics clear PFnet >= PFNET_LIVE_FLOOR - checked at the moment of a NEW
entry, in _maybe_place_real_entry (long intraday), _maybe_place_real_short_
entry (short intraday), and _maybe_place_real_swing_entry (swing).

As of 2026-09-30's actual registry data:
  - universal_score (long intraday, the only tag every WATCHLIST symbol
    uses): PFnet 0.05 - BLOCKED.
  - range_short_staged_ladder / trend_down_momentum_short (short RANGE/
    TREND): PFnet 0.21 / 0.09 - BLOCKED.
  - gap_and_go (swing): PFnet 1.65 (gap_and_go_swing) - ALLOWED.
  - minervini_vcp (swing): PFnet 0.908 (minervini_trend_template_vcp,
    confirmed via that entry's own `source` field pointing at
    main.py's minervini_vcp_entry_signal/minervini_vcp_exit_reason) -
    BLOCKED, just under the floor.

This gate is deliberately scoped to NEW entries only - existing open
real positions' exit/SL-sync/auto-heal machinery is completely untouched
(see _is_strategy_viable_for_real_money's own module comment for why this
is not a new kill switch either).

Run: pytest tests/test_pfnet_real_money_gate.py -v
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


# ---- _is_strategy_viable_for_real_money: pure classification --------------

def test_unregistered_or_unknown_tag_fails_closed():
    assert main._is_strategy_viable_for_real_money(None) is False
    assert main._is_strategy_viable_for_real_money("") is False
    assert main._is_strategy_viable_for_real_money("orb-not-a-real-tag") is False


def test_universal_score_is_not_viable_today():
    assert main._is_strategy_viable_for_real_money("orb-universal-score") is False


def test_range_and_trend_short_are_not_viable_today():
    assert main._is_strategy_viable_for_real_money("orb-range-short") is False
    assert main._is_strategy_viable_for_real_money("orb-trend-short") is False


def test_swing_gap_and_go_is_viable_today():
    assert main._is_strategy_viable_for_real_money("orb-swing-gap-and-go") is True
    assert main._is_strategy_viable_for_real_money("gap_and_go") is True


def test_swing_minervini_vcp_is_not_viable_today():
    # 0.908, just under the 1.0 floor - a deliberately close case, not a
    # blowout, so a future off-by-a-fraction bug in is_viable()'s >= check
    # would actually be caught here.
    assert main._is_strategy_viable_for_real_money("minervini_vcp") is False


def test_a_registered_strategy_with_no_metrics_yet_fails_closed():
    import dataclasses
    import strategy_registry as sr
    original = list(sr.REGISTRY)
    idx = next(i for i, s in enumerate(sr.REGISTRY) if s.name == "universal_score")
    sr.REGISTRY[idx] = dataclasses.replace(sr.REGISTRY[idx], metrics=None)
    try:
        assert main._is_strategy_viable_for_real_money("orb-universal-score") is False
    finally:
        sr.REGISTRY[:] = original


# ---- _maybe_place_real_entry (long intraday) -------------------------------

def _insert_paper_signal(conn, symbol, strategy="orb-universal-score", qty=10):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, strategy) "
        "VALUES (?, '2026-09-30', 'long', 100.0, 90.0, 90.0, 130.0, ?, ?, 1.0, '5m', ?)",
        (symbol, qty, main.time.time(), strategy),
    )
    conn.commit()


def test_long_entry_blocked_for_universal_score():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS", strategy="orb-universal-score")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry") as mock_entry:
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            mock_entry.assert_not_called()
            assert conn.execute("SELECT 1 FROM real_positions WHERE symbol='TESTSTOCK.NS'").fetchone() is None
            attempt = conn.execute(
                "SELECT status FROM real_trades WHERE symbol='TESTSTOCK.NS' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert attempt["status"] == "skipped_strategy_not_viable"
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_long_entry_proceeds_when_gate_is_patched_viable():
    # Confirms the gate is the thing blocking it above, not some other
    # unrelated failure - same fixture, gate patched True, entry proceeds.
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal(conn, "TESTSTOCK.NS", strategy="orb-universal-score")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("main._is_strategy_viable_for_real_money", return_value=True), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target",
                       return_value={"ok": True, "order_id": "T1", "target_price": 130.0}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            assert conn.execute("SELECT 1 FROM real_positions WHERE symbol='TESTSTOCK.NS'").fetchone() is not None
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


# ---- _maybe_place_real_short_entry (short intraday) ------------------------

def _insert_paper_short_signal(conn, symbol, strategy="orb-range-short", qty=10):
    conn.execute(
        "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, qty, entry_ts, fx_to_inr, interval, strategy) "
        "VALUES (?, '2026-09-30', 'short', 100.0, 110.0, 110.0, ?, ?, 1.0, '5m', ?)",
        (symbol, qty, main.time.time(), strategy),
    )
    conn.commit()


def test_short_entry_blocked_for_range_short():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_short_signal(conn, "TESTSTOCK.NS", strategy="orb-range-short")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_short_entry") as mock_entry:
                main._maybe_place_real_short_entry(conn, "TESTSTOCK.NS")
            mock_entry.assert_not_called()
            assert conn.execute("SELECT 1 FROM real_positions_short WHERE symbol='TESTSTOCK.NS'").fetchone() is None
            attempt = conn.execute(
                "SELECT status FROM real_trades WHERE symbol='TESTSTOCK.NS' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert attempt["status"] == "skipped_strategy_not_viable"
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_short_entry_blocked_for_trend_short_too():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_short_signal(conn, "TESTSTOCK.NS", strategy="orb-trend-short")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_short_entry") as mock_entry:
                main._maybe_place_real_short_entry(conn, "TESTSTOCK.NS")
            mock_entry.assert_not_called()
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


# ---- _maybe_place_real_swing_entry ------------------------------------------

def test_swing_gap_and_go_entry_proceeds_viable():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}):
                main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            assert conn.execute("SELECT 1 FROM real_positions_swing WHERE symbol='TESTSTOCK.NS'").fetchone() is not None
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)


def test_swing_minervini_vcp_entry_blocked_not_viable():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry") as mock_entry:
                main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "minervini_vcp")
            mock_entry.assert_not_called()
            assert conn.execute("SELECT 1 FROM real_positions_swing WHERE symbol='TESTSTOCK.NS'").fetchone() is None
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)


# ---- The gate must never touch anything about an ALREADY-open position ----

def test_gate_does_not_exist_on_exit_or_sl_sync_functions():
    # Structural guard: _is_strategy_viable_for_real_money must only be
    # referenced from the three NEW-entry functions, never from an
    # exit/SL-sync/auto-heal function - a position already open must
    # never be abandoned by this gate.
    import inspect
    for fn in (main._maybe_place_real_exit, main._maybe_place_real_short_exit,
               main._maybe_sync_real_stop_loss, main._maybe_sync_real_stop_loss_short):
        assert "_is_strategy_viable_for_real_money" not in inspect.getsource(fn)
