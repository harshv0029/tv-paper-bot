"""Unit tests for fo_rsi2_validation_status / /fo-rsi2-validation-status -
the explicit user-set bar (2026-09-16, AskUserQuestion: 4 weeks minimum
AND 30+ closed trades total) the RSI2-options paper engine must clear
before real-order wiring is even considered. See main.py's own comment
above FO_RSI2_VALIDATION_MIN_DAYS for why meeting this is necessary,
not sufficient.

Run: pytest tests/ -v
"""
import os
import tempfile
import time
from contextlib import closing

import main


def _with_temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = main.DB_PATH
    main.DB_PATH = path
    main.init_db()
    return old_path


def _restore_db(old_path):
    main.DB_PATH = old_path


def _insert_trade(conn, ts, action, strategy="rsi2_premium_reversion"):
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, 'X:RSI2FO', ?, 75, 100.0, 1.0, ?, '{}')",
        (ts, action, strategy),
    )
    conn.commit()


def test_no_trades_yet_never_meets_criteria():
    old_path = _with_temp_db()
    try:
        with closing(main.get_db()) as conn:
            status = main.fo_rsi2_validation_status(conn)
        assert status["first_paper_trade_ts"] is None
        assert status["closed_trades"] == 0
        assert status["meets_minimum_criteria"] is False
    finally:
        _restore_db(old_path)


def test_enough_days_but_not_enough_closed_trades():
    old_path = _with_temp_db()
    try:
        old_ts = time.time() - 40 * 86400  # 40 days ago, past the 28-day bar
        with closing(main.get_db()) as conn:
            _insert_trade(conn, old_ts, "buy")
            for _ in range(5):
                _insert_trade(conn, time.time(), "sell")
            status = main.fo_rsi2_validation_status(conn)
        assert status["days_elapsed"] >= main.FO_RSI2_VALIDATION_MIN_DAYS
        assert status["closed_trades"] == 5
        assert status["meets_minimum_criteria"] is False
    finally:
        _restore_db(old_path)


def test_enough_closed_trades_but_not_enough_days():
    old_path = _with_temp_db()
    try:
        recent_ts = time.time() - 2 * 86400  # only 2 days ago
        with closing(main.get_db()) as conn:
            _insert_trade(conn, recent_ts, "buy")
            for _ in range(35):
                _insert_trade(conn, time.time(), "sell")
            status = main.fo_rsi2_validation_status(conn)
        assert status["closed_trades"] >= main.FO_RSI2_VALIDATION_MIN_CLOSED_TRADES
        assert status["days_elapsed"] < main.FO_RSI2_VALIDATION_MIN_DAYS
        assert status["meets_minimum_criteria"] is False
    finally:
        _restore_db(old_path)


def test_meets_criteria_when_both_bars_cleared():
    old_path = _with_temp_db()
    try:
        old_ts = time.time() - 30 * 86400
        with closing(main.get_db()) as conn:
            _insert_trade(conn, old_ts, "buy")
            for _ in range(30):
                _insert_trade(conn, time.time(), "sell")
            status = main.fo_rsi2_validation_status(conn)
        assert status["meets_minimum_criteria"] is True
    finally:
        _restore_db(old_path)


def test_buy_rows_are_not_counted_as_closed_trades():
    old_path = _with_temp_db()
    try:
        old_ts = time.time() - 30 * 86400
        with closing(main.get_db()) as conn:
            for _ in range(30):
                _insert_trade(conn, old_ts, "buy")
            status = main.fo_rsi2_validation_status(conn)
        assert status["closed_trades"] == 0
        assert status["meets_minimum_criteria"] is False
    finally:
        _restore_db(old_path)


def test_other_strategies_trades_are_not_counted():
    old_path = _with_temp_db()
    try:
        old_ts = time.time() - 30 * 86400
        with closing(main.get_db()) as conn:
            for _ in range(30):
                _insert_trade(conn, old_ts, "sell", strategy="long_straddle")
            status = main.fo_rsi2_validation_status(conn)
        assert status["closed_trades"] == 0
        assert status["first_paper_trade_ts"] is None
    finally:
        _restore_db(old_path)


def test_endpoint_returns_the_same_shape():
    old_path = _with_temp_db()
    try:
        result = main.fo_rsi2_validation_status_endpoint()
        assert set(result.keys()) == {
            "first_paper_trade_ts", "days_elapsed", "days_required",
            "closed_trades", "closed_trades_required", "meets_minimum_criteria",
        }
    finally:
        _restore_db(old_path)
