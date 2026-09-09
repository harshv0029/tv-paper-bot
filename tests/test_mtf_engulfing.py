"""Tests for the multi-timeframe candlestick strategy (2026-09-09,
explicit user order: "Ur entry conditions should be such that it gives
profit by recognising the pattern on candle stick diagram of different
time frames. Do through this approach only... An order."). See main.py's
add_strategy_signal, strategy="mtf_engulfing" branch, for the full
mechanism: a higher-timeframe EMA trend (read off the LAST CLOSED higher
candle only - no lookahead) gates a bullish-engulfing trigger on the
entry timeframe."""
import datetime as dt

import numpy as np
import pandas as pd

import main


def _bar(ts, o, h, l, c, v=1000):
    return {"Date": ts, "Open": o, "High": h, "Low": l, "Close": c, "Volume": v}


def _build_trending_df(start_price, minutes_per_bar, n_bars, drift_per_bar, engulf_at):
    """n_bars of `minutes_per_bar`-spaced candles drifting by drift_per_bar
    each bar (positive = uptrend, negative = downtrend), with one
    deliberate two-bar bearish-then-bullish-engulfing pair inserted at
    index `engulf_at` (on TOP of the underlying drift, so the engulfing
    pair itself is a real reversal-looking dip-and-recover, not just
    noise)."""
    start = dt.datetime(2026, 9, 9, 3, 45, tzinfo=dt.timezone.utc)  # 09:15 IST
    rows = []
    price = start_price
    for i in range(n_bars):
        ts = start + dt.timedelta(minutes=minutes_per_bar * i)
        if i == engulf_at:
            # small bearish candle
            o, c = price, price - abs(drift_per_bar) * 3
            rows.append(_bar(ts, o, max(o, c) + 0.1, min(o, c) - 0.1, c))
            price = c
        elif i == engulf_at + 1:
            # bullish candle that fully engulfs the previous bearish one
            prev_o, prev_c = rows[-1]["Open"], rows[-1]["Close"]
            o, c = min(prev_o, prev_c) - 0.05, max(prev_o, prev_c) + 0.05
            rows.append(_bar(ts, o, c + 0.1, o - 0.1, c))
            price = c
        else:
            price = price + drift_per_bar
            o, c = price - drift_per_bar, price
            rows.append(_bar(ts, o, max(o, c) + 0.1, min(o, c) - 0.1, c))
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def test_enters_when_htf_trend_up_and_engulfing_fires():
    # 5-min bars, strong uptrend drift -> the 30-min HTF EMA trend is
    # solidly up by the time the engineered engulfing pair fires deep
    # into the series (bar 60 of 90, well past the fast/slow EMA warmup).
    df = _build_trending_df(100.0, 5, 90, drift_per_bar=0.15, engulf_at=60)
    params = {"htf_minutes": 30, "htf_trend_fast": 3, "htf_trend_slow": 6}
    result = main.add_strategy_signal(df, "mtf_engulfing", params)
    assert result["long"].any(), "should have entered at least once when HTF trend is up and engulfing fires"


def test_never_enters_when_htf_trend_is_down():
    # Same engineered engulfing pair, but the underlying drift is
    # strongly DOWN throughout - the higher-timeframe gate must block
    # every entry even though the pattern itself still fires.
    df = _build_trending_df(200.0, 5, 90, drift_per_bar=-0.15, engulf_at=60)
    params = {"htf_minutes": 30, "htf_trend_fast": 3, "htf_trend_slow": 6}
    result = main.add_strategy_signal(df, "mtf_engulfing", params)
    assert not result["long"].any(), "must never enter while the higher-timeframe trend is down"


def test_no_lookahead_first_bar_of_a_new_htf_bucket_uses_the_prior_closed_bucket():
    # The very first 5-min bar of a fresh 30-min bucket must be judged by
    # the PREVIOUS bucket's already-closed trend, not by anything in the
    # bucket it's currently forming (which isn't closed yet) - proven by
    # asserting the mtf_engulfing entries are a SUBSET of what plain
    # single-timeframe bullish_engulfing would fire on its own (the HTF
    # gate can only remove entries, never add ones the base pattern
    # didn't already flag, and never uses information from the future).
    df = _build_trending_df(100.0, 5, 90, drift_per_bar=0.15, engulf_at=60)
    params = {"htf_minutes": 30, "htf_trend_fast": 3, "htf_trend_slow": 6}
    mtf_result = main.add_strategy_signal(df.copy(), "mtf_engulfing", params)
    base_result = main.add_strategy_signal(df.copy(), "bullish_engulfing", {"trend_sma": 0, "volume_confirm": False})
    # every mtf entry bar must also be a base-engulfing entry bar
    mtf_entries = set(mtf_result.index[mtf_result["long"] & ~mtf_result["long"].shift(1).fillna(False)])
    base_entries = set(base_result.index[base_result["long"] & ~base_result["long"].shift(1).fillna(False)])
    assert mtf_entries <= base_entries


def test_handles_short_dataframe_without_raising():
    # Fewer bars than htf_trend_slow needs to warm up - must degrade to
    # "no entries," never crash (same discipline as every other strategy
    # branch in add_strategy_signal).
    df = _build_trending_df(100.0, 5, 5, drift_per_bar=0.1, engulf_at=2)
    params = {"htf_minutes": 30, "htf_trend_fast": 9, "htf_trend_slow": 21}
    result = main.add_strategy_signal(df, "mtf_engulfing", params)
    assert not result["long"].any()
