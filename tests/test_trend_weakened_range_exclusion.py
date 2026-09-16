"""Tests for the second half of the 2026-09-14 validation-replay fix (see
_range_regime_stop_loss's own docstring for the first half - the
degenerate stop distance). Root cause: the trend_weakened exit check
(_auto_signal_core) assumes "went long because trend was UP, exit if it
has since flipped DOWN" - correct for orb_breakout/bullish_engulfing and
TREND-regime universal_score entries, but backwards for RANGE mean-
reversion, which goes long BECAUSE the short-term trend is already down
(_vwap_mean_reversion_entry fires on a dip below the lower VWAP band).
Confirmed against the 52-symbol/60-day validation replay: trend_weakened
fired on ~47% of ALL exits (nearly as many as stop_hit) and closed RANGE
trades almost immediately regardless of the (separately fixed) stop
distance. Fix: a new entry_regime column on signal_state, set at entry,
gates the check - only "range" suppresses it; every other value (a real
"trend" tag, or NULL for orb_breakout/bullish_engulfing/backfilled/pre-
fix-resurrected positions) keeps the check exactly as before."""
import math
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


def _insert_open_position(conn, symbol: str, entry_regime):
    """Entry far from both stop and target so this fixture's mild price
    decline can never trigger stop_hit/target_hit - isolates whatever
    exit_reason actually fires to the trend_weakened check under test.

    `day` must match the FIXED clock `_run_exit_check` patches
    (`_FixedUtcNow`), not the real wall clock: `_auto_signal_core` deletes
    any signal_state row whose `day` differs from its own computed
    today_str before running any exit check at all (stale-day guard). This
    used to call `main.ist_now()` (real, unpatched time) - which happened
    to match `_FixedUtcNow`'s 2026-09-14 on the day this test was written,
    then silently made `test_trend_weakened_still_closes_a_trend_regime_position`
    and `..._with_unknown_regime` fail on every later date (row gets wiped
    pre-exit-check, falls through to the unrelated entry-signal path,
    returns action_taken="no_signal" instead of "exited_trend_weakened") -
    found 2026-09-16 verifying a background agent's report against a clean
    origin/main checkout, main.py's actual exit logic was NOT at fault."""
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, entry_regime) "
        "VALUES (?, ?, 'long', 100.0, 80.0, 80.0, 130.0, 10, ?, 1.0, '5m', ?)",
        (symbol, _fixed_ist_day_str(), main.time.time(), entry_regime),
    )
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, ?, 'buy', 10, 100.0, 1.0, 'test-universal-score', '{}')",
        (main.time.time(), symbol),
    )
    conn.commit()


class _FixedUtcNow(__import__("datetime").datetime):
    _fixed = __import__("datetime").datetime(2026, 9, 14, 5, 0, 0)  # UTC -> 10:30 IST

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _fixed_ist_day_str() -> str:
    """The IST calendar day _auto_signal_core computes from _FixedUtcNow's
    fixed clock, matching main.ist_now()'s own UTC->IST math - used to
    stamp fixture rows so they survive _auto_signal_core's stale-day guard
    (see _insert_open_position's docstring)."""
    ist = _FixedUtcNow._fixed + __import__("datetime").timedelta(minutes=main.IST_OFFSET_MIN)
    return ist.strftime("%Y-%m-%d")


def _mild_downtrend_fixture(days: int = 5, bars_per_day: int = 20) -> pd.DataFrame:
    """A gentle, steady decline (sma_fast will read below sma_slow) that
    never approaches the 80/130 stop/target set in _insert_open_position -
    isolates the trend_weakened path from stop_hit/target_hit entirely."""
    rows = []
    i = 0
    base_dates = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-14"]
    for day in base_dates[:days]:
        base = pd.Timestamp(f"{day} 03:45:00")  # UTC -> 09:15 IST
        for b in range(bars_per_day):
            ts = base + pd.Timedelta(minutes=5 * b)
            close = 100 - 0.03 * i + 0.1 * math.sin(i / 2.0)
            rows.append({
                "Date": ts, "Open": close, "High": close + 0.2, "Low": close - 0.2,
                "Close": close, "Volume": 1000 + (i % 10) * 10,
            })
            i += 1
    return pd.DataFrame(rows)


def _run_exit_check(symbol: str):
    fixture = _mild_downtrend_fixture()
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("main._trend_confidence", return_value=0.99):
        return main._auto_signal_core(symbol, currency="INR")


def test_trend_weakened_does_not_close_a_range_regime_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, "RANGETEST.NS", entry_regime="range")
    result = _run_exit_check("RANGETEST.NS")
    assert result["action_taken"] != "exited_trend_weakened", (
        "a RANGE-regime position must not be closed by the TREND-oriented "
        f"trend_weakened check - got {result}"
    )


def test_trend_weakened_still_closes_a_trend_regime_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, "TRENDTEST.NS", entry_regime="trend")
    result = _run_exit_check("TRENDTEST.NS")
    assert result["action_taken"] == "exited_trend_weakened"


def test_trend_weakened_still_closes_a_position_with_unknown_regime():
    """NULL entry_regime (orb_breakout/bullish_engulfing, a real-position
    governance backfill, or a pre-fix journal resurrection) must keep the
    OLD behavior - never silently suppressed just because the regime
    isn't known."""
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, "LEGACYTEST.NS", entry_regime=None)
    result = _run_exit_check("LEGACYTEST.NS")
    assert result["action_taken"] == "exited_trend_weakened"
