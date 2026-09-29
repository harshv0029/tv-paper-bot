"""Tests for the Power Play / High Tight Flag strategy (2026-09-29,
explicit user instruction "Build Power Play first" after a second reading
pass over docs/Trade Like a Stock Market Wizard (2013).pdf surfaced it as
the clearest genuinely-new strategy candidate - see
docs/minervini_book_notes.txt's CHAPTER 10 (REST) section). Unlike
Minervini VCP, Power Play is NOT gated by the Trend Template or
fundamentals: an explosive prior move (>=100% in <=40 trading days), a
tight sideways flag (<=25% deep, final leg <=10%), then a breakout.
Not wired into main.py's live scan/scheduler/order path - see
strategy_registry.py's "registering != trading" principle."""
import numpy as np
import pandas as pd

import main


def _power_play_fixture(launch_bars=25, launch_start=100.0, launch_peak=210.0,
                         breakout_close=216.0, breakout_vol=3000.0):
    """25 bars of a launch move (+110% here by default, comfortably over
    the 100% floor) whose peak sits at the very last launch bar, followed
    by a 15-bar flag oscillating within 25% of that peak (tightening to
    within 10% over its final 5 bars), then a breakout bar clearing the
    flag's high on a volume surge."""
    launch = np.linspace(launch_start, launch_peak, launch_bars)
    flag_mid = np.concatenate([
        np.array([205.0, 192.0, 203.0, 194.0, 201.0, 196.0, 199.0, 197.0, 198.0, 197.5]),
        np.array([208.0, 209.0, 207.5, 209.5, 208.5]),
    ])
    close = np.concatenate([launch, flag_mid, [breakout_close]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = breakout_vol
    return pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })


# ---- _find_power_play_setup / power_play_entry_signal -----------------------

def test_power_play_entry_fires_on_a_clean_launch_flag_breakout():
    df = _power_play_fixture()
    sig = main.power_play_entry_signal(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_power_play_entry_none_without_a_qualifying_launch():
    # Flat prior history instead of a >=100% move - same flag/breakout shape.
    launch_flat = np.full(25, 200.0) + np.linspace(0, 1, 25)
    flag_mid = np.concatenate([
        np.array([205.0, 192.0, 203.0, 194.0, 201.0, 196.0, 199.0, 197.0, 198.0, 197.5]),
        np.array([208.0, 209.0, 207.5, 209.5, 208.5]),
    ])
    close = np.concatenate([launch_flat, flag_mid, [216.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_when_flag_is_too_deep():
    # Same launch, but the flag corrects ~40% - well past the 25% ceiling.
    launch = np.linspace(100.0, 210.0, 25)
    flag_mid = np.concatenate([
        np.array([205.0, 130.0, 200.0, 135.0, 198.0, 140.0, 196.0, 145.0, 194.0, 150.0]),
        np.array([205.0, 206.0, 204.5, 206.5, 205.5]),
    ])
    close = np.concatenate([launch, flag_mid, [212.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_without_a_breakout():
    df = _power_play_fixture(breakout_close=205.0)  # still inside the flag's own high (211)
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_without_a_volume_surge():
    df = _power_play_fixture(breakout_vol=1000.0)  # no surge over the trailing average
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_on_insufficient_history():
    df = _power_play_fixture().iloc[-15:].reset_index(drop=True)
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_stop_uses_flag_low():
    df = _power_play_fixture()
    sig = main.power_play_entry_signal(df)
    setup = main._find_power_play_setup(df)
    assert sig["stop_loss"] == setup["consol_low"]


# ---- power_play_exit_reason ---------------------------------------------

def test_power_play_exit_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 102.0, 104.0],
    })
    reason, running_max = main.power_play_exit_reason(df, "2026-01-02", 90.0, 5.0, 100.0)
    assert reason is None
    assert running_max == 104.0


def test_power_play_exit_trail_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 130.0, 119.0],
    })
    # running_max ratchets to 130 after bar 2; trail_stop = 130 - 2*5 = 120 > initial_stop(90)
    reason, running_max = main.power_play_exit_reason(df, "2026-01-02", 90.0, 5.0, 130.0)
    assert reason == "trail_stop_hit"
    assert running_max == 130.0


def test_power_play_exit_max_hold_timeout():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS + 2).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason(df, dates[0], 50.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_power_play_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS - 5).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason(df, dates[0], 50.0, 5.0, 100.0)
    assert reason is None
