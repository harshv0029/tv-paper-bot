"""Tests for /daily-summary's real_entry_reason field (2026-09-28,
explicit user ask: "add a column mentioning ... why not moved to real
money trade"). _maybe_place_real_entry already logs every skip via
_log_real_attempt (real_trades, side='B') - this just surfaces the most
recent one per open paper position instead of leaving trade-view's
Reason column blank/static.

Run: pytest tests/test_daily_summary_real_entry_reason.py -v
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


def _insert_open_paper_position(conn, symbol="RELIANCE.NS"):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
        "(?, ?, 'long', 100.0, 95.0, 95.0, 115.0, 5, ?, 1.0, '5m')",
        (symbol, main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
    )
    conn.commit()


def _insert_real_trades_attempt(conn, symbol, status, detail=None):
    conn.execute(
        "INSERT INTO real_trades (ts, day, symbol, side, status, detail) VALUES (?, ?, ?, 'B', ?, ?)",
        (main.time.time(), main.ist_now().strftime("%Y-%m-%d"), symbol, status, detail),
    )
    conn.commit()


def _open_position(result, symbol="RELIANCE.NS"):
    return next(p for p in result["open_positions"] if p["symbol"] == symbol)


def test_reason_is_none_when_the_position_is_already_real_tracked():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES ('RELIANCE.NS', 'RELIANCE-EQ', 5, 100.0, 'E1', ?, ?)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch.object(main, "is_real_trading_enabled", return_value=True):
        result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    assert _open_position(result)["real_entry_reason"] is None


def test_reason_reports_real_trading_off():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
    with patch.object(main, "is_real_trading_enabled", return_value=False):
        result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    assert "OFF" in _open_position(result)["real_entry_reason"]


def test_reason_surfaces_the_latest_logged_skip():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
        _insert_real_trades_attempt(conn, "RELIANCE.NS", "skipped_real_daily_loss_cap_hit",
                                     detail="real P&L today Rs-500 vs joint cap Rs450")
    with patch.object(main, "is_real_trading_enabled", return_value=True):
        result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    reason = _open_position(result)["real_entry_reason"]
    assert "real daily loss cap already hit" in reason
    assert "Rs-500" in reason


def test_reason_picks_the_most_recent_attempt_not_an_earlier_one():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
        _insert_real_trades_attempt(conn, "RELIANCE.NS", "skipped_no_live_tick")
        _insert_real_trades_attempt(conn, "RELIANCE.NS", "skipped_real_daily_loss_cap_hit")
    with patch.object(main, "is_real_trading_enabled", return_value=True):
        result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    reason = _open_position(result)["real_entry_reason"]
    assert "real daily loss cap already hit" in reason


def test_reason_none_logged_yet():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
    with patch.object(main, "is_real_trading_enabled", return_value=True):
        result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    assert "no real-entry attempt logged" in _open_position(result)["real_entry_reason"]
