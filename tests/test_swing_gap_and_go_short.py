"""Tests for the swing engine's Gap and Go SHORT mirror ("gap down and
go", 2026-09-29, explicit user instruction "Prep short mirror for others
too" per CLAUDE.md's 2026-09-28 standing thumb rule - task #23, the last
of the long strategies still missing a short mirror this session).
main.gap_and_go_entry_signal_short / main.gap_and_go_exit_reason_short
reuse every constant from the long side (gap_and_go_entry_signal /
gap_and_go_exit_reason, see tests/test_swing_gap_and_go.py) verbatim,
only the comparison directions are inverted. Not wired into main.py's
live scan/scheduler/order path - see strategy_registry.py's "registering
!= trading" principle."""
import numpy as np
import pandas as pd
import pytest

import main


def _daily_df(opens, highs, lows, closes, volumes):
    n = len(closes)
    return pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes,
    })


def _flat_series(base, n, seed):
    rng = np.random.default_rng(seed)
    return base + rng.normal(0, 0.05, n)


class TestGapAndGoEntrySignalShort:
    def test_fires_on_a_volume_confirmed_gap_down_that_holds_and_closes_weak(self):
        n_chop = 60
        rng = np.random.default_rng(11)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        # Gap down 3% (>= SWING_GAP_PCT_THRESHOLD=2.0), closes red, closes in
        # the lower half of its Low-Open range, on 2x average volume
        # (>= SWING_VOL_MULT=1.5).
        gap_open = prev_close * 0.97
        gap_close = gap_open * 0.99
        gap_low = gap_close * 0.995
        gap_high = prev_close * 0.995

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_high)
        lows = np.append(chop - 0.15, gap_low)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        signal = main.gap_and_go_entry_signal_short(df)

        assert signal is not None
        assert signal["entry_price"] == pytest.approx(gap_close)
        assert signal["gap_high"] == pytest.approx(gap_high)
        assert signal["stop_loss"] > signal["entry_price"]

    def test_no_signal_when_gap_is_too_small(self):
        n_chop = 60
        rng = np.random.default_rng(12)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        # Only a 0.5% gap down - below SWING_GAP_PCT_THRESHOLD=2.0.
        gap_open = prev_close * 0.995
        gap_close = gap_open * 0.99
        gap_low = gap_close * 0.995

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, prev_close * 0.999)
        lows = np.append(chop - 0.15, gap_low)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal_short(df) is None

    def test_no_signal_when_gap_day_bounces_green(self):
        n_chop = 60
        rng = np.random.default_rng(13)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        gap_open = prev_close * 0.97
        # Closes ABOVE the open (green bounce day - held_gap fails).
        gap_close = gap_open * 1.005
        gap_low = gap_open * 0.99

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_close * 1.01)
        lows = np.append(chop - 0.15, gap_low)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal_short(df) is None

    def test_no_signal_without_volume_confirmation(self):
        n_chop = 60
        rng = np.random.default_rng(14)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        gap_open = prev_close * 0.97
        gap_close = gap_open * 0.99
        gap_low = gap_close * 0.995

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, prev_close * 0.995)
        lows = np.append(chop - 0.15, gap_low)
        closes = np.append(chop, gap_close)
        # Volume only at the 20d average, not 1.5x it.
        volumes = np.append(np.full(n_chop, 100000.0), 100000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal_short(df) is None

    def test_returns_none_with_too_few_bars(self):
        df = _daily_df(*([np.array([100.0, 101.0])] * 4), np.array([1000.0, 1000.0]))
        assert main.gap_and_go_entry_signal_short(df) is None


class TestGapAndGoExitReasonShort:
    def _base_df(self, n=80, seed=15):
        closes = _flat_series(100.0, n, seed)
        return _daily_df(closes, closes + 0.2, closes - 0.2, closes, np.full(n, 100000.0))

    def test_stop_hit_takes_priority(self):
        df = self._base_df()
        df.loc[df.index[-1], "Close"] = 150.0  # spikes through both stop and gap_high
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason_short(df, entry_day, stop_loss=110.0, gap_high=105.0)
        assert reason == "stop_hit"

    def test_gap_filled_when_close_breaks_gap_high_but_not_stop(self):
        df = self._base_df()
        df.loc[df.index[-1], "Close"] = 106.0  # above gap_high=105, below stop=110
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason_short(df, entry_day, stop_loss=110.0, gap_high=105.0)
        assert reason == "gap_filled"

    def test_no_exit_while_price_holds_below_both_levels(self):
        df = self._base_df(n=10)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason_short(df, entry_day, stop_loss=150.0, gap_high=140.0)
        assert reason is None

    def test_max_hold_timeout_after_60_trading_days(self):
        df = self._base_df(n=main.SWING_MAX_HOLD_DAYS + 5)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason_short(df, entry_day, stop_loss=200.0, gap_high=200.0)
        assert reason == "max_hold_timeout"

    def test_no_max_hold_timeout_before_60_trading_days(self):
        df = self._base_df(n=main.SWING_MAX_HOLD_DAYS - 5)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason_short(df, entry_day, stop_loss=200.0, gap_high=200.0)
        assert reason is None
