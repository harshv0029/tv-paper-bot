"""Tests for the Power Play short mirror ("power fade", 2026-09-29,
explicit user instruction "Prep short mirror for others too" per
CLAUDE.md's 2026-09-28 standing thumb rule). Mirrors
_find_power_play_setup/power_play_entry_signal/power_play_exit_reason
direction only - see main.py's own POWER_PLAY_CRASH_MIN_LOSS_PCT_SHORT
comment for why the launch/crash magnitude threshold (a halving, not
"-100%") is a log-symmetric mirror rather than a naive reuse of the long
side's +100% gain requirement. Not wired into main.py's live scan/
scheduler/order path - see strategy_registry.py's "registering != trading"
principle."""
import numpy as np
import pandas as pd

import main


def _power_play_short_fixture(crash_bars=25, crash_start=210.0, crash_trough=100.0,
                               breakdown_close=84.0, breakdown_vol=3000.0):
    """25 bars of a crash (-52%, comfortably over the 50% halving floor)
    whose trough sits at the very last crash bar, followed by a 15-bar
    flag oscillating within 25% of that trough (tightening to within 10%
    over its final 5 bars), then a breakdown bar clearing the flag's low
    on a volume surge - the mirror image of tests/test_power_play.py's
    own _power_play_fixture."""
    crash = np.linspace(crash_start, crash_trough, crash_bars)
    flag_mid = np.concatenate([
        np.array([105.0, 118.0, 107.0, 116.0, 109.0, 114.0, 111.0, 113.0, 112.0, 112.5]),
        np.array([92.0, 91.0, 92.5, 90.5, 91.5]),
    ])
    close = np.concatenate([crash, flag_mid, [breakdown_close]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = breakdown_vol
    return pd.DataFrame({
        "Open": close + 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })


# ---- _find_power_play_setup_short / power_play_entry_signal_short -----------

def test_power_play_short_entry_fires_on_a_clean_crash_flag_breakdown():
    df = _power_play_short_fixture()
    sig = main.power_play_entry_signal_short(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] > sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_power_play_short_entry_none_without_a_qualifying_crash():
    # Flat prior history instead of a >=50% halving - same flag/breakdown shape.
    crash_flat = np.full(25, 100.0) - np.linspace(0, 1, 25)
    flag_mid = np.concatenate([
        np.array([105.0, 118.0, 107.0, 116.0, 109.0, 114.0, 111.0, 113.0, 112.0, 112.5]),
        np.array([92.0, 91.0, 92.5, 90.5, 91.5]),
    ])
    close = np.concatenate([crash_flat, flag_mid, [84.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close + 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal_short(df) is None


def test_power_play_short_entry_none_when_flag_is_too_deep():
    # Same crash, but the flag swings ~40% - well past the 25% ceiling.
    crash = np.linspace(210.0, 100.0, 25)
    flag_mid = np.concatenate([
        np.array([105.0, 180.0, 110.0, 175.0, 115.0, 170.0, 120.0, 165.0, 125.0, 150.0]),
        np.array([95.0, 94.0, 95.5, 93.5, 94.5]),
    ])
    close = np.concatenate([crash, flag_mid, [88.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close + 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal_short(df) is None


def test_power_play_short_entry_none_without_a_breakdown():
    df = _power_play_short_fixture(breakdown_close=95.0)  # still inside the flag's own low (~89.5)
    assert main.power_play_entry_signal_short(df) is None


def test_power_play_short_entry_none_without_a_volume_surge():
    df = _power_play_short_fixture(breakdown_vol=1000.0)  # no surge over the trailing average
    assert main.power_play_entry_signal_short(df) is None


def test_power_play_short_entry_none_on_insufficient_history():
    df = _power_play_short_fixture().iloc[-15:].reset_index(drop=True)
    assert main.power_play_entry_signal_short(df) is None


def test_power_play_short_entry_stop_uses_flag_high():
    df = _power_play_short_fixture()
    sig = main.power_play_entry_signal_short(df)
    setup = main._find_power_play_setup_short(df)
    assert sig["stop_loss"] == setup["consol_high"]


# ---- power_play_exit_reason_short ------------------------------------------

def test_power_play_short_exit_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 98.0, 96.0],
    })
    reason, running_min = main.power_play_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 100.0)
    assert reason is None
    assert running_min == 96.0


def test_power_play_short_exit_trail_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 70.0, 81.0],
    })
    # running_min ratchets to 70 after bar 2; trail_stop = 70 + 2*5 = 80 < initial_stop(110)
    reason, running_min = main.power_play_exit_reason_short(df, "2026-01-02", 110.0, 5.0, 70.0)
    assert reason == "trail_stop_hit"
    assert running_min == 70.0


def test_power_play_short_exit_max_hold_timeout():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS + 2).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_power_play_short_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS - 5).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason_short(df, dates[0], 150.0, 5.0, 100.0)
    assert reason is None
