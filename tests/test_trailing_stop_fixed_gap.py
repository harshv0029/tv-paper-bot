"""Tests for the fixed-0.5R-gap trailing stop (2026-09-09, explicit user
instruction: "trailing SL should keep 0.5R always"). Replaces the earlier
Chandelier-Exit/ATR(14) trail width with a constant TRAIL_ACTIVATE_R * R
gap below the highest close since entry - see main.py's
_trailing_stop_target docstring and docs/TRADING_CONSTRAINTS.md
"Trailing stop loss" for the full rationale."""
import datetime as dt

import pandas as pd

import main


def _today_df(closes, start_hour=9, start_minute=15, freq_min=5):
    """A minimal today_df: just Close + mins (minutes since local midnight),
    the only two columns _trailing_stop_target actually reads."""
    mins = [start_hour * 60 + start_minute + i * freq_min for i in range(len(closes))]
    return pd.DataFrame({"Close": closes, "mins": mins})


_ENTRY_TS = dt.datetime(2026, 9, 9, 3, 45, tzinfo=dt.timezone.utc).timestamp()  # 09:15 IST
_TZ_OFF = 330  # IST


def test_returns_none_below_activation_threshold():
    # entry 100, initial stop 98 -> R = 2; 0.5R = 1 -> activates at 101
    today_df = _today_df([100.0, 100.5, 100.9])  # never reaches 101
    cand = main._trailing_stop_target(today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF)
    assert cand is None


def test_activates_at_exactly_breakeven_when_gain_hits_0_5R():
    # entry 100, R = 2 -> activation at last_close = 101 (exactly 0.5R)
    today_df = _today_df([100.0, 100.5, 101.0])
    cand = main._trailing_stop_target(today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF)
    assert cand == 100.0 * (1 + main.TRAIL_BREAKEVEN_BUFFER_PCT / 100)


def test_stop_stays_exactly_0_5R_below_the_peak_as_price_extends():
    # entry 100, initial stop 98 -> R = 2, 0.5R = 1
    # peak so far = 106 -> fixed-gap stop should be 106 - 1 = 105
    today_df = _today_df([100.0, 103.0, 106.0, 104.5])  # pulled back after the peak
    cand = main._trailing_stop_target(today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF)
    assert cand == 105.0
    # gap from the peak is always exactly TRAIL_ACTIVATE_R * R, never wider/narrower
    assert 106.0 - cand == main.TRAIL_ACTIVATE_R * 2.0


def test_stop_never_proposed_below_breakeven_floor():
    # tiny R (0.4) so 0.5R gap could theoretically dip the trail stop just
    # below breakeven right after activation - the breakeven floor must win
    today_df = _today_df([100.0, 100.2])  # entry 100, R = 0.8 (stop 99.2) -> activates at 100.4
    cand = main._trailing_stop_target(today_df, 100.0, 99.2, _ENTRY_TS, _TZ_OFF)
    # activation not yet reached at 100.2 (needs 100.4)
    assert cand is None
    today_df2 = _today_df([100.0, 100.4])
    cand2 = main._trailing_stop_target(today_df2, 100.0, 99.2, _ENTRY_TS, _TZ_OFF)
    breakeven = 100.0 * (1 + main.TRAIL_BREAKEVEN_BUFFER_PCT / 100)
    assert cand2 >= breakeven


def test_only_bars_since_this_trades_own_entry_count_toward_the_peak():
    # a spike BEFORE entry_ts must not count toward "highest close since entry"
    today_df = pd.DataFrame({
        "Close": [110.0, 100.0, 103.0],  # pre-entry spike to 110, then entry, then 103
        "mins": [9 * 60, 9 * 60 + 15, 9 * 60 + 20],  # first bar is before entry_mins (09:15)
    })
    cand = main._trailing_stop_target(today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF)
    # R = 2, 0.5R = 1; peak-since-entry = 103 (NOT 110) -> stop = 102
    assert cand == 102.0


def test_r_le_0_returns_none_never_raises():
    today_df = _today_df([100.0, 105.0])
    assert main._trailing_stop_target(today_df, 100.0, 100.0, _ENTRY_TS, _TZ_OFF) is None
    assert main._trailing_stop_target(today_df, 100.0, 101.0, _ENTRY_TS, _TZ_OFF) is None
