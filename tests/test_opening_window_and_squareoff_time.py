"""Tests for two 2026-09-21 explicit user instructions:
1. "Make sure that u do not trade between 9:15-9:30. As they are
   exceptional behaviour" - no NEW entries in the first
   NO_ENTRY_WINDOW_AFTER_OPEN_MINUTES minutes after open_min.
2. "All intraday trade should be closed by 3:15pm" - squareoff_min
   default moved from 15:20 to 15:15.
Reuses the bullish-engulfing entry fixture pattern from
test_round_trip_cost_gate.py, parametrized on the fixed "now" clock so
the entry bar's own timestamp can be placed at different points in the
session."""
import datetime as real_datetime
import os
import tempfile
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _bullish_engulfing_fixture(entry_bar_time: str):
    """Same shape as test_round_trip_cost_gate.py's fixture, but the final
    (entry) bar's timestamp is parametrized - 23 flat baseline bars end
    5 minutes before entry_bar_time, a bearish bar, then the bullish-
    engulfing entry bar exactly at entry_bar_time."""
    entry_ts = pd.Timestamp(entry_bar_time)
    base = entry_ts - pd.Timedelta(minutes=5 * 24)
    rows = []
    for i in range(23):
        c = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        rows.append({
            "Date": base + pd.Timedelta(minutes=5 * i), "Open": c, "High": c + 0.1,
            "Low": c - 0.1, "Close": c, "Volume": 1000,
        })
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 23), "Open": 101.0, "High": 101.1,
        "Low": 99.6, "Close": 99.7, "Volume": 1000,
    })
    rows.append({
        "Date": entry_ts, "Open": 99.5, "High": 101.6, "Low": 99.4, "Close": 101.5, "Volume": 3000,
    })
    return pd.DataFrame(rows)


def _run_at(now_ist: str, entry_bar_ist: str):
    """now_ist/entry_bar_ist: 'HH:MM' IST on 2026-09-09."""
    _fresh_db()
    now_h, now_m = (int(x) for x in now_ist.split(":"))
    now_utc = real_datetime.datetime(2026, 9, 9, now_h, now_m, 0) - real_datetime.timedelta(
        minutes=main.IST_OFFSET_MIN
    )

    class _Fixed(real_datetime.datetime):
        _fixed = now_utc

        @classmethod
        def utcnow(cls):
            return cls._fixed

    fixture = _bullish_engulfing_fixture(f"2026-09-09 {entry_bar_ist}:00")
    with patch("main.dt.datetime", _Fixed), patch("main.fetch_ohlc", return_value=fixture):
        return main._auto_signal_core(
            "TESTSTOCK.NS", currency="INR", strategy="bullish_engulfing", trend_sma=0, rr=10.0,
        )


def test_no_entry_at_9_20_inside_the_opening_window():
    result = _run_at(now_ist="09:20", entry_bar_ist="09:20")
    assert result["action_taken"] == "no_new_entries_opening_volatility"


def test_entry_allowed_at_9_30_exactly_the_window_boundary():
    result = _run_at(now_ist="09:30", entry_bar_ist="09:30")
    assert result["action_taken"] == "entered_long"


def test_entry_allowed_well_after_the_opening_window():
    result = _run_at(now_ist="11:15", entry_bar_ist="11:15")
    assert result["action_taken"] == "entered_long"


def _insert_open_position(conn, symbol: str, entry_ts: float):
    # Entry far from both stop and target, and a flat/noisy fixture, so
    # only the squareoff-time check under test can fire - mirrors
    # test_exit_uses_live_ltp.py's own _insert_open_position helper.
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
        "VALUES (?, '2026-09-09', 'long', 100.0, 90.0, 90.0, 130.0, 10, ?, 1.0, '5m')",
        (symbol, entry_ts),
    )
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, ?, 'buy', 10, 100.0, 1.0, 'test-universal-score', '{}')",
        (entry_ts, symbol),
    )
    conn.commit()


def _run_exit_check_at(now_ist: str):
    now_h, now_m = (int(x) for x in now_ist.split(":"))
    now_utc = real_datetime.datetime(2026, 9, 9, now_h, now_m, 0) - real_datetime.timedelta(
        minutes=main.IST_OFFSET_MIN
    )

    class _Fixed(real_datetime.datetime):
        _fixed = now_utc

        @classmethod
        def utcnow(cls):
            return cls._fixed

    base_utc = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
    fixture = pd.DataFrame([
        {"Date": base_utc + pd.Timedelta(minutes=5 * i),
         "Open": 100.0, "High": 100.2, "Low": 99.8, "Close": 100.0, "Volume": 1000}
        for i in range(80)
    ])
    entry_ts = base_utc.timestamp()
    with patch("main.dt.datetime", _Fixed), patch("main.fetch_ohlc", return_value=fixture), \
         patch("main._trend_confidence", return_value=0.0):
        _fresh_db()
        with main.closing(main.get_db()) as conn:
            _insert_open_position(conn, "TESTSTOCK.NS", entry_ts)
        # max_hold_minutes set high so stale_timeout (which would
        # otherwise fire first - entry is at market open, "now" is hours
        # later) doesn't mask the squareoff-time check under test.
        return main._auto_signal_core("TESTSTOCK.NS", currency="INR", max_hold_minutes=100000.0)


def test_squareoff_fires_at_915pm_under_the_new_default_not_the_old_920():
    # 15:17 (917 min) is PAST the new 15:15 default but still BEFORE the
    # old 15:20 default - proves the default actually moved, not just
    # that squareoff eventually fires.
    result = _run_exit_check_at("15:17")
    assert result["action_taken"] == "exited_eod_squareoff"


def test_squareoff_does_not_fire_before_915pm():
    result = _run_exit_check_at("15:10")
    assert result["action_taken"] != "exited_eod_squareoff"
