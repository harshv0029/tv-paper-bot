"""
Unit tests for the swing engine's Gap and Go signal functions
(main.gap_and_go_entry_signal / main.gap_and_go_exit_reason), added
2026-09-16 after Gap and Go became the first research strategy this
session to clear the production pool bar (PFnet>1, n>=100 - see
docs/STRATEGY_LOG.md's "Gap and Go, 5-year window" entry, PFnet 1.65,
n=142). These functions are a deliberate line-for-line port of the
validated research workflow's math (swing-gap-and-go-5y-research.yml) -
every test here hand-verifies a scenario against that same logic, not
against main.py's own implementation, so a future accidental change to
either one shows up as a test failure rather than silently drifting.

Run: pytest tests/ -v
"""
import os
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd
import pytest

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _daily_df(opens, highs, lows, closes, volumes):
    n = len(closes)
    return pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes,
    })


def _flat_series(base, n, seed):
    rng = np.random.default_rng(seed)
    return base + rng.normal(0, 0.05, n)


class TestGapAndGoEntrySignal:
    def test_fires_on_a_volume_confirmed_gap_up_that_holds_and_closes_strong(self):
        n_chop = 60
        rng = np.random.default_rng(1)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        # Gap up 3% (>= SWING_GAP_PCT_THRESHOLD=2.0), closes green, closes in
        # the upper half of its Open-High range, on 2x average volume
        # (>= SWING_VOL_MULT=1.5).
        gap_open = prev_close * 1.03
        gap_close = gap_open * 1.01
        gap_high = gap_close * 1.005
        gap_low = prev_close * 1.005

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_high)
        lows = np.append(chop - 0.15, gap_low)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        signal = main.gap_and_go_entry_signal(df)

        assert signal is not None
        assert signal["entry_price"] == pytest.approx(gap_close)
        assert signal["gap_low"] == pytest.approx(gap_low)
        assert signal["stop_loss"] < signal["entry_price"]

    def test_no_signal_when_gap_is_too_small(self):
        n_chop = 60
        rng = np.random.default_rng(2)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        # Only a 0.5% gap - below SWING_GAP_PCT_THRESHOLD=2.0.
        gap_open = prev_close * 1.005
        gap_close = gap_open * 1.01
        gap_high = gap_close * 1.005

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_high)
        lows = np.append(chop - 0.15, prev_close * 1.001)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal(df) is None

    def test_no_signal_when_gap_day_fades_red(self):
        n_chop = 60
        rng = np.random.default_rng(3)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        gap_open = prev_close * 1.03
        # Closes BELOW the open (red gap day - held_gap fails).
        gap_close = gap_open * 0.995
        gap_high = gap_open * 1.01

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_high)
        lows = np.append(chop - 0.15, gap_close * 0.99)
        closes = np.append(chop, gap_close)
        volumes = np.append(np.full(n_chop, 100000.0), 250000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal(df) is None

    def test_no_signal_without_volume_confirmation(self):
        n_chop = 60
        rng = np.random.default_rng(4)
        chop = 100.0 + np.cumsum(rng.normal(0, 0.2, n_chop))
        prev_close = chop[-1]
        gap_open = prev_close * 1.03
        gap_close = gap_open * 1.01
        gap_high = gap_close * 1.005

        opens = np.append(chop - 0.05, gap_open)
        highs = np.append(chop + 0.15, gap_high)
        lows = np.append(chop - 0.15, prev_close * 1.005)
        closes = np.append(chop, gap_close)
        # Volume only at the 20d average, not 1.5x it.
        volumes = np.append(np.full(n_chop, 100000.0), 100000.0)

        df = _daily_df(opens, highs, lows, closes, volumes)
        assert main.gap_and_go_entry_signal(df) is None

    def test_returns_none_with_too_few_bars(self):
        df = _daily_df(*([np.array([100.0, 101.0])] * 4), np.array([1000.0, 1000.0]))
        assert main.gap_and_go_entry_signal(df) is None


class TestGapAndGoExitReason:
    def _base_df(self, n=80, seed=5):
        closes = _flat_series(100.0, n, seed)
        return _daily_df(closes, closes + 0.2, closes - 0.2, closes, np.full(n, 100000.0))

    def test_stop_hit_takes_priority(self):
        df = self._base_df()
        df.loc[df.index[-1], "Close"] = 50.0  # crashes through both stop and gap_low
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason(df, entry_day, stop_loss=90.0, gap_low=95.0)
        assert reason == "stop_hit"

    def test_gap_filled_when_close_breaks_gap_low_but_not_stop(self):
        df = self._base_df()
        df.loc[df.index[-1], "Close"] = 94.0  # below gap_low=95, above stop=90
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason(df, entry_day, stop_loss=90.0, gap_low=95.0)
        assert reason == "gap_filled"

    def test_no_exit_while_price_holds_above_both_levels(self):
        df = self._base_df(n=10)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason(df, entry_day, stop_loss=50.0, gap_low=60.0)
        assert reason is None

    def test_max_hold_timeout_after_60_trading_days(self):
        df = self._base_df(n=main.SWING_MAX_HOLD_DAYS + 5)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason(df, entry_day, stop_loss=1.0, gap_low=1.0)
        assert reason == "max_hold_timeout"

    def test_no_max_hold_timeout_before_60_trading_days(self):
        df = self._base_df(n=main.SWING_MAX_HOLD_DAYS - 5)
        entry_day = str(df["Date"].iloc[0].date())
        reason = main.gap_and_go_exit_reason(df, entry_day, stop_loss=1.0, gap_low=1.0)
        assert reason is None


class TestSwingWatchlist:
    def test_validated_52_universe_is_preserved_exactly(self):
        # Guards against silent drift in the ORIGINAL validated subset (the
        # PFnet 1.65/n=142 finding) even though SWING_WATCHLIST itself was
        # deliberately widened past it (2026-09-22, explicit user
        # instruction) - _SWING_VALIDATED_52 is what any future re-backtest/
        # holdout logic (e.g. idea 8's top-15-by-PF check) should still
        # anchor to.
        unevidenced_sample = [
            "ADANIPOWER.NS", "ASIANPAINT.NS", "BAJAJ-AUTO.NS", "BEL.NS", "BHARTIARTL.NS", "BPCL.NS",
            "BRITANNIA.NS", "COALINDIA.NS", "DABUR.NS", "DRREDDY.NS", "EICHERMOT.NS", "HAL.NS",
            "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "ICICIGI.NS", "ICICIPRULI.NS", "IOC.NS",
            "IRFC.NS", "JINDALSTEL.NS", "KOTAKBANK.NS", "LT.NS", "LUPIN.NS", "MARICO.NS",
            "MOTHERSON.NS", "NESTLEIND.NS", "PNB.NS", "POLYCAB.NS", "SBIN.NS", "SRF.NS",
            "SUNPHARMA.NS", "TATACONSUM.NS", "TATAPOWER.NS", "TATASTEEL.NS", "TORNTPHARM.NS",
            "UBL.NS", "UPL.NS", "VEDL.NS", "WIPRO.NS", "ZYDUSLIFE.NS",
        ]
        expected = sorted(set(main.NSE_STOCK_PARAM_OVERRIDES.keys()) | set(unevidenced_sample))
        assert main._SWING_VALIDATED_52 == expected
        assert len(main._SWING_VALIDATED_52) == 52

    def test_swing_watchlist_widened_to_full_nifty_200_superset(self):
        # 2026-09-22, explicit user instruction after being told the extra
        # ~150 symbols are unvalidated for Gap and Go: widen anyway, paper
        # and real together, no prior backtest gate. This test just
        # confirms the widening did what it was supposed to (NIFTY 200
        # equities, same asset class, validated subset still included) -
        # it is NOT a claim that the strategy has been shown to work on
        # the wider set.
        assert set(main._SWING_VALIDATED_52) <= set(main.SWING_WATCHLIST)
        assert set(main.NSE_FULL_UNIVERSE) <= set(main.SWING_WATCHLIST)
        assert len(main.SWING_WATCHLIST) >= len(main.NSE_FULL_UNIVERSE)
        assert all(s.endswith(".NS") for s in main.SWING_WATCHLIST)


class TestDeployedNotionalIncludesSwing:
    def test_swing_open_position_counts_toward_deployed_notional(self):
        _fresh_db()
        with closing(main.get_db()) as conn:
            before = main.deployed_notional(conn)
            conn.execute(
                "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, "
                "initial_stop_loss, gap_low, qty, entry_ts, fx_to_inr) "
                "VALUES ('TEST.NS', 'gap_and_go', '2024-01-01', 100.0, 90.0, 95.0, 10, 0, 1.0)"
            )
            conn.commit()
            after = main.deployed_notional(conn)
        assert after == pytest.approx(before + 1000.0)


class TestSwingScannerWiring:
    def test_scheduler_tick_calls_run_swing_scan(self):
        import inspect
        src = inspect.getsource(main._scheduler_tick)
        assert "_run_swing_scan(conn)" in src

    def test_swing_trades_are_tagged_for_shared_loss_cap_visibility(self):
        # SWING_STRATEGY_TAG must start with ORB_STRATEGY_PREFIX so
        # today_realized_pnl()'s `WHERE strategy LIKE 'orb-%'` query picks up
        # swing's realized P&L for the shared daily-loss-cap halt.
        assert main.SWING_STRATEGY_TAG.startswith(main.ORB_STRATEGY_PREFIX)
