"""Tests for the lower-circuit entry guard (2026-09-28, explicit user
instruction backed by a live finding: POLICYBZR.NS, 2026-09-23 - repeated
paper entries at what all the evidence points to as a circuit-locked
price, which the existing _liquidity_gate (tape-flatness/zero-volume)
did not reliably catch since a circuit-locked stock can still show
nonzero volume/turnover and non-identical closes within any single
3-bar lookback, e.g. during the burst that drove it into the lock).

_likely_lower_circuit_locked is a separate, distinct check: down
LOWER_CIRCUIT_GUARD_PCT% or more from the PREVIOUS trading day's own
close - the actual basis NSE's circuit bands are set against, not tape
flatness.

Run: pytest tests/test_lower_circuit_guard.py -v
"""
import pandas as pd

import main


def _df(rows):
    """rows: list of (date_local, close) tuples, oldest first."""
    return pd.DataFrame({
        "date_local": [r[0] for r in rows],
        "Close": [r[1] for r in rows],
    })


def test_flags_a_stock_down_beyond_the_guard_threshold():
    # Previous day closed 1500.0, today sitting at 1320.1 - a ~12% drop,
    # the real POLICYBZR.NS shape (entry_price_native 1357.9 in the real
    # trade log, exit prices frozen at 1282.3/1320.1).
    df = _df([("2026-09-22", 1500.0), ("2026-09-23", 1320.1)])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is True


def test_does_not_flag_a_normal_move():
    df = _df([("2026-09-22", 1500.0), ("2026-09-23", 1470.0)])  # -2%
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_boundary_exactly_at_the_threshold_is_flagged():
    prior = 1000.0
    today = prior * (1 - main.LOWER_CIRCUIT_GUARD_PCT / 100)
    df = _df([("2026-09-22", prior), ("2026-09-23", today)])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is True


def test_just_inside_the_threshold_is_not_flagged():
    prior = 1000.0
    today = prior * (1 - (main.LOWER_CIRCUIT_GUARD_PCT - 0.5) / 100)
    df = _df([("2026-09-22", prior), ("2026-09-23", today)])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_an_upper_circuit_style_move_is_never_flagged():
    # This guard is specifically about LOWER circuits - a stock up 20%
    # must never be blocked by it (a separate, symmetric upper-circuit
    # concept exists but is out of scope for this ask).
    df = _df([("2026-09-22", 1000.0), ("2026-09-23", 1200.0)])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_fails_open_with_no_prior_trading_day_in_the_data():
    # A newly-listed symbol, or the very first day this app has data for
    # it - refusing every symbol with thin history is worse than
    # occasionally missing a genuine circuit day.
    df = _df([("2026-09-23", 100.0)])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_fails_open_on_an_empty_dataframe():
    df = pd.DataFrame({"date_local": [], "Close": []})
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_fails_open_when_date_local_column_is_missing():
    df = pd.DataFrame({"Close": [100.0, 90.0]})
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is False


def test_uses_the_most_recent_prior_day_not_an_older_one():
    # Two prior days present - must compare against the LATEST prior
    # close (yesterday), not an arbitrary earlier one.
    df = _df([
        ("2026-09-19", 500.0),   # far prior day - irrelevant
        ("2026-09-22", 1500.0),  # yesterday - the one that matters
        ("2026-09-23", 1320.1),
    ])
    assert main._likely_lower_circuit_locked(df, "2026-09-23") is True
    # If it had wrongly used the far-prior close (500.0), 1320.1 would be
    # a gain, not a drop, and this would incorrectly read False.


# ---- Wiring check: applied at the shared, regime-agnostic level -----------

def test_wired_into_auto_signal_core_for_both_regimes():
    # Source-level invariant, same pattern as the liquidity-gate wiring
    # it sits next to: confirms the guard is ANDed into entry_signal for
    # BOTH the RANGE and TREND branches, not just one.
    import inspect
    src = inspect.getsource(main._auto_signal_core)
    assert "circuit_locked = _likely_lower_circuit_locked(df, today_str)" in src
    assert 'entry_signal = bool(range_entry) and liquidity_gate_ok and not circuit_locked' in src
    assert 'entry_signal = score_result["entry_allowed"] and not circuit_locked' in src
