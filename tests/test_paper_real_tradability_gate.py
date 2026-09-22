"""Tests for require_real_tradability (2026-09-22, explicit user
instruction: "make sure that paper trading also follow the exact replica
of real money trade engine... not a separate logic for giving false
hope") - a paper "entered_long" for an NSE equity must be blocked on the
same two existence gates _maybe_place_real_entry itself enforces (a live
Kotak tick, not T1/T2T-restricted), using the same status strings, so the
paper book never shows an open position real trading would have refused
outright. See _auto_signal_core's own docstring for the full reasoning
and why this deliberately does NOT touch entry price or capital/loss-
budget sizing.

Run: pytest tests/test_paper_real_tradability_gate.py -v
"""
import datetime as real_datetime
import inspect
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


class _FixedUtcNow(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 5, 45, 0)  # UTC -> 11:15 IST, mid-session

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _bullish_engulfing_fixture():
    # Same shape as test_confidence_proportional_sizing.py's own fixture -
    # a quiet flat series ending in a real bullish engulfing bar, reliably
    # triggers "entered_long" for strategy="bullish_engulfing".
    base = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
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
        "Date": base + pd.Timedelta(minutes=5 * 24), "Open": 99.5, "High": 101.6,
        "Low": 99.4, "Close": 101.5, "Volume": 3000,
    })
    return pd.DataFrame(rows)


def _run(symbol="TESTSTOCK.NS", **kwargs):
    fixture = _bullish_engulfing_fixture()
    with patch("main.dt.datetime", _FixedUtcNow), patch("main.fetch_ohlc", return_value=fixture):
        return main._auto_signal_core(
            symbol, currency="INR", strategy="bullish_engulfing", trend_sma=0, rr=10.0, **kwargs,
        )


def test_default_false_never_checks_live_tick_or_t1_unchanged_for_every_existing_caller():
    # Backward compat, explicit per the docstring: /auto-signal, backtests,
    # and the validation replay must keep entering on pure historical/
    # on-demand data with no live Kotak tick to check - proven here by NOT
    # mocking kotak_live_feed at all (a real import/call would raise or
    # return {} for an unresolved symbol) and still expecting entry to
    # succeed, plus flagging the symbol T1-restricted and confirming that's
    # ignored too when the flag is off.
    _fresh_db()
    with closing(main.get_db()) as conn:
        main._flag_if_t1_restricted(conn, "TESTSTOCK.NS", "RMS:Rule: Check T1 holdings...No Holdings Present")
    result = _run()
    assert result["action_taken"] == "entered_long"


def test_require_real_tradability_blocks_a_t1_restricted_symbol():
    _fresh_db()
    with closing(main.get_db()) as conn:
        main._flag_if_t1_restricted(conn, "TESTSTOCK.NS", "RMS:Rule: Check T1 holdings...No Holdings Present")
    result = _run(require_real_tradability=True)
    assert result["action_taken"] == "skipped_t1_restricted"
    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT 1 FROM signal_state WHERE symbol = 'TESTSTOCK.NS'").fetchone() is None


def test_require_real_tradability_blocks_when_no_live_tick():
    _fresh_db()
    with patch("kotak_live_feed.get_live_ticks", return_value={}):
        result = _run(require_real_tradability=True)
    assert result["action_taken"] == "skipped_no_live_tick"
    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT 1 FROM signal_state WHERE symbol = 'TESTSTOCK.NS'").fetchone() is None


def test_require_real_tradability_allows_entry_once_a_live_tick_exists_and_not_restricted():
    _fresh_db()
    tick = {"TESTSTOCK.NS": {"ltp": 101.5, "trading_symbol": "TESTSTOCK-EQ"}}
    with patch("kotak_live_feed.get_live_ticks", return_value=tick):
        result = _run(require_real_tradability=True)
    assert result["action_taken"] == "entered_long"


def test_scheduler_only_requires_real_tradability_for_ns_equities():
    # NSE equities are the only symbols _maybe_place_real_entry itself ever
    # mirrors (its own asset_class != "nse_equity" check skips everything
    # else) - a symbol real trading can't touch at all yet (indices/
    # commodities/US) has no real gate to replicate, so must stay
    # unconditional (paper keeps testing every symbol continuously).
    src = inspect.getsource(main._scheduler_tick)
    assert 'require_real_tradability=cfg["symbol"].endswith(".NS")' in src
