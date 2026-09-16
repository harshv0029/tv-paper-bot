"""Unit tests for fo_option_strategy.py's RSI(2) mean-reversion signal
detection (2026-09-16, first strategy wired to run on an option's own
premium candles, per explicit user choice). Synthetic OHLC fixtures
only - real values experimentally verified against the actual functions
before being baked into these assertions (not hand-computed by eye),
same discipline as every other synthetic-data test this session.

Run: pytest tests/ -v
"""
import numpy as np
import pandas as pd

import fo_option_strategy as strat


def _make_df(closes, spread=0.5, start="2026-01-01", freq="5min"):
    closes = np.asarray(closes, dtype=float)
    dates = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC")
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": closes + spread, "Low": closes - spread,
        "Close": closes, "Volume": 10,
    })


def _uptrend_then_dip_df():
    # 204 bars of a steady uptrend, then one sharp one-bar dip - deep
    # enough to push RSI(2) below 10 while the close still sits well
    # above its own 200-bar SMA (experimentally verified: rsi2=3.6,
    # close=152.9, sma200=131.3).
    base = 100 + np.arange(204) * 0.3
    dip = base[-1] - 8.0
    return _make_df(np.concatenate([base, [dip]]))


def test_entry_signal_fires_on_a_deep_dip_within_an_uptrend():
    df = _uptrend_then_dip_df()
    sig = strat.rsi2_mean_reversion_entry_signal(df)
    assert sig is not None
    assert sig["rsi2"] < strat.RSI_ENTRY_MAX
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr"] > 0


def test_entry_signal_is_none_with_insufficient_history():
    df = _uptrend_then_dip_df().iloc[:50].reset_index(drop=True)
    assert strat.rsi2_mean_reversion_entry_signal(df) is None


def test_entry_signal_is_none_exactly_one_bar_short_of_min_lookback():
    df = _uptrend_then_dip_df().iloc[: strat.MIN_LOOKBACK_BARS - 1].reset_index(drop=True)
    assert strat.rsi2_mean_reversion_entry_signal(df) is None


def test_entry_signal_is_none_in_a_downtrend_even_with_a_low_rsi():
    # A steady DOWNTREND (fails the trend filter: close must be > SMA200)
    # - RSI(2) will naturally run low throughout a downtrend too, so this
    # specifically confirms the trend filter (not just the RSI gate)
    # is doing real work, not being trivially satisfied by any dip.
    base = 200 - np.arange(205) * 0.3
    df = _make_df(base)
    assert strat.rsi2_mean_reversion_entry_signal(df) is None


def test_entry_signal_is_none_without_a_deep_enough_dip():
    # Same uptrend, no dip at all - RSI(2) stays high, entry gate never opens.
    base = 100 + np.arange(205) * 0.3
    df = _make_df(base)
    assert strat.rsi2_mean_reversion_entry_signal(df) is None


def _entry_fixture():
    df = _uptrend_then_dip_df()
    sig = strat.rsi2_mean_reversion_entry_signal(df)
    return df, sig["entry_bar_ts"], sig["stop_loss"]


def test_exit_reason_is_stop_hit_when_close_falls_through_the_stop():
    df, entry_ts, stop = _entry_fixture()
    next_date = df["Date"].iloc[-1] + pd.Timedelta(minutes=5)
    row = pd.DataFrame({
        "Date": [next_date], "Open": [df["Close"].iloc[-1]], "High": [df["Close"].iloc[-1]],
        "Low": [stop - 1], "Close": [stop - 1], "Volume": [10],
    })
    df2 = pd.concat([df, row], ignore_index=True)
    assert strat.rsi2_mean_reversion_exit_reason(df2, entry_ts, stop) == "stop_hit"


def test_exit_reason_is_rsi_reverted_after_a_strong_rally():
    df, entry_ts, stop = _entry_fixture()
    next_date = df["Date"].iloc[-1] + pd.Timedelta(minutes=5)
    last_close = df["Close"].iloc[-1]
    row = pd.DataFrame({
        "Date": [next_date], "Open": [last_close], "High": [last_close + 10],
        "Low": [last_close], "Close": [last_close + 10], "Volume": [10],
    })
    df2 = pd.concat([df, row], ignore_index=True)
    assert strat.rsi2_mean_reversion_exit_reason(df2, entry_ts, stop) == "rsi_reverted"


def test_exit_reason_is_max_hold_timeout_after_enough_flat_bars():
    df, entry_ts, stop = _entry_fixture()
    last_close = df["Close"].iloc[-1]
    rows = []
    d = df["Date"].iloc[-1]
    for _ in range(strat.MAX_HOLD_BARS):
        d = d + pd.Timedelta(minutes=5)
        rows.append({"Date": d, "Open": last_close, "High": last_close + 0.2,
                      "Low": last_close - 0.2, "Close": last_close, "Volume": 10})
    df2 = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    assert strat.rsi2_mean_reversion_exit_reason(df2, entry_ts, stop) == "max_hold_timeout"


def test_exit_reason_is_none_before_any_condition_is_met():
    df, entry_ts, stop = _entry_fixture()
    last_close = df["Close"].iloc[-1]
    next_date = df["Date"].iloc[-1] + pd.Timedelta(minutes=5)
    row = pd.DataFrame({
        "Date": [next_date], "Open": [last_close], "High": [last_close + 0.2],
        "Low": [last_close - 0.2], "Close": [last_close], "Volume": [10],
    })
    df2 = pd.concat([df, row], ignore_index=True)
    assert strat.rsi2_mean_reversion_exit_reason(df2, entry_ts, stop) is None


def test_exit_reason_is_none_when_the_entry_bar_is_no_longer_in_the_dataframe():
    # A contract that dropped out of the candle universe and got
    # re-added later could plausibly have a gap where its old entry bar
    # is no longer present - must fail safe (None), never raise or guess.
    df, entry_ts, stop = _entry_fixture()
    truncated = df.iloc[-5:].reset_index(drop=True)  # entry bar long gone
    assert strat.rsi2_mean_reversion_exit_reason(truncated, entry_ts, stop) is None


def test_exit_reason_handles_timezone_aware_timestamps_correctly():
    # Regression test for a real bug found while writing these tests:
    # comparing a tz-aware pandas Timestamp via np.datetime64() silently
    # drops tzinfo and the lookup then never matches anything, making
    # every exit check return None regardless of real conditions.
    df, entry_ts, stop = _entry_fixture()
    assert entry_ts.tzinfo is not None
    next_date = df["Date"].iloc[-1] + pd.Timedelta(minutes=5)
    row = pd.DataFrame({
        "Date": [next_date], "Open": [df["Close"].iloc[-1]], "High": [df["Close"].iloc[-1]],
        "Low": [stop - 1], "Close": [stop - 1], "Volume": [10],
    })
    df2 = pd.concat([df, row], ignore_index=True)
    result = strat.rsi2_mean_reversion_exit_reason(df2, entry_ts, stop)
    assert result is not None, "tz-aware entry_bar_ts must still be found in df"
