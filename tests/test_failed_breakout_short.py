"""Tests for the Failed Breakout ("bull trap") short strategy (2026-09-30,
explicit user instruction "Read about it and backtest"). Not wired into
main.py's live scan/scheduler/order path - see strategy_registry.py's
"registering != trading" principle. RESEARCH-STAGE ONLY until a
full-universe validation replay reports real numbers.

Standard definition: price breaks above an established resistance ceiling,
the breakout fails to hold within a few sessions, and price reverses back
below that ceiling - trapping the breakout buyers. Short entry fires on
the failure/reversal confirmation, not the breakout itself.

Run: pytest tests/test_failed_breakout_short.py -v
"""
import numpy as np
import pandas as pd

import main


def _failed_breakout_fixture(resistance=200.0, breakout_pct=3.0, days_since_breakout=2,
                              base_days=60, exclude_days=10, reversal_close=195.0):
    """A flat/ranging base establishing `resistance` as the ceiling, then
    (within the last `exclude_days`) a breakout bar clearing it by
    `breakout_pct`%, then a reversal back below it by today - the canonical
    failed-breakout shape."""
    base = np.full(base_days, resistance - 5.0) + np.sin(np.linspace(0, 6, base_days))
    base[-1] = resistance  # the ceiling itself gets touched but not exceeded in the base window
    recent_days = exclude_days
    breakout_day_idx = recent_days - days_since_breakout - 1
    recent = np.full(recent_days, resistance - 3.0)
    recent[breakout_day_idx] = resistance * (1 + breakout_pct / 100)
    # fill the days between breakout and today with a gentle fade
    for k in range(breakout_day_idx + 1, recent_days):
        recent[k] = resistance - 1.0
    close = np.concatenate([base, recent, [reversal_close]])
    high = close + 1.0
    low = close - 1.0
    volume = np.full(len(close), 1000.0)
    dates = pd.date_range("2023-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"Open": close - 0.2, "High": high, "Low": low, "Close": close,
                          "Volume": volume, "Date": dates})


# ---- _find_failed_breakout_setup / failed_breakout_entry_signal_short ------

def test_entry_fires_on_a_clean_failed_breakout():
    df = _failed_breakout_fixture()
    sig = main.failed_breakout_entry_signal_short(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] > sig["entry_price"]  # short: stop ABOVE entry
    assert sig["atr_at_entry"] > 0


def test_entry_none_when_breakout_never_happened():
    # Flat throughout - no bar ever cleared resistance.
    close = np.full(75, 200.0) + np.sin(np.linspace(0, 6, 75))
    df = pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": np.full(75, 1000.0),
        "Date": pd.date_range("2023-01-01", periods=75, freq="B").strftime("%Y-%m-%d"),
    })
    assert main.failed_breakout_entry_signal_short(df) is None


def test_entry_none_when_breakout_has_not_failed_yet():
    # Breakout happened, but today's close is still ABOVE resistance -
    # the failure/reversal hasn't been confirmed.
    df = _failed_breakout_fixture(reversal_close=210.0)
    assert main.failed_breakout_entry_signal_short(df) is None


def test_entry_none_when_breakout_too_long_ago():
    df = _failed_breakout_fixture(days_since_breakout=main.FAILED_BREAKOUT_MAX_DAYS_SINCE_BREAKOUT + 5)
    assert main.failed_breakout_entry_signal_short(df) is None


def test_entry_none_when_breakout_too_small():
    df = _failed_breakout_fixture(breakout_pct=0.1)  # under FAILED_BREAKOUT_MIN_BREAKOUT_PCT
    assert main.failed_breakout_entry_signal_short(df) is None


def test_entry_none_on_insufficient_history():
    df = _failed_breakout_fixture(base_days=5)  # far too short for the resistance lookback
    assert main.failed_breakout_entry_signal_short(df) is None


def test_stop_sits_above_the_breakout_highs_own_overshoot():
    df = _failed_breakout_fixture()
    sig = main.failed_breakout_entry_signal_short(df)
    setup = main._find_failed_breakout_setup(df)
    assert sig["stop_loss"] == setup["breakout_high"]


# ---- failed_breakout_exit_reason_short -------------------------------------

def test_exit_trail_stop_hit_when_price_bounces_back_up():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-03", "2026-01-04"],
        "Close": [100.0, 80.0, 92.0],
    })
    # running_min ratchets to 80 after bar 2; trail_stop = 80 + 2*5 = 90 < initial_stop(110)
    reason, running_min = main.failed_breakout_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 80.0)
    assert reason == "trail_stop_hit"
    assert running_min == 80.0


def test_exit_none_while_price_keeps_falling():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-03"],
        "Close": [100.0, 95.0],
    })
    reason, running_min = main.failed_breakout_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 100.0)
    assert reason is None
    assert running_min == 95.0


def test_exit_max_hold_timeout():
    dates = pd.bdate_range("2026-01-02", periods=main.FAILED_BREAKOUT_MAX_HOLD_DAYS + 2).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.failed_breakout_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=main.FAILED_BREAKOUT_MAX_HOLD_DAYS - 5).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.failed_breakout_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason is None


def test_exit_stop_never_ratchets_back_up_against_a_bounce():
    # running_min already at 80; a bounce to 85 must not loosen the trail.
    df = pd.DataFrame({"Date": ["2026-01-05"], "Close": [85.0]})
    reason, running_min = main.failed_breakout_exit_reason_short(df, "2026-01-02", 110.0, 2.0, 80.0)
    # trail_stop = 80 + 2*2 = 84; close 85 >= 84 -> hit
    assert reason == "trail_stop_hit"
    assert running_min == 80.0  # min(80, 85) stays 80, never loosens toward 85
