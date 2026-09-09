"""Tests for the heikin_ashi_vwap strategy (2026-09-09, explicit user
instruction: "assign one ai agent that researches the web pages and
social media for getting strategies and back test it" - sourced from
liberatedstocktrader.com, the same site already cited for
bullish_engulfing's own numbers: VWAP + Heikin Ashi on 5-min intraday
"outperforming 93% of stocks using a buy-and-hold strategy"). See
main.py's add_strategy_signal, strategy="heikin_ashi_vwap" branch."""
import datetime as dt

import pandas as pd

import main


def _bar(ts, o, h, l, c, v=1000):
    return {"Date": ts, "Open": o, "High": h, "Low": l, "Close": c, "Volume": v}


def _uptrend_df(n=40, start=100.0, step=0.5):
    start_ts = dt.datetime(2026, 9, 9, 3, 45, tzinfo=dt.timezone.utc)  # 09:15 IST
    rows = []
    price = start
    for i in range(n):
        ts = start_ts + dt.timedelta(minutes=5 * i)
        o = price
        c = price + step
        rows.append(_bar(ts, o, max(o, c) + 0.05, min(o, c) - 0.05, c))
        price = c
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def _downtrend_df(n=40, start=200.0, step=0.5):
    start_ts = dt.datetime(2026, 9, 9, 3, 45, tzinfo=dt.timezone.utc)
    rows = []
    price = start
    for i in range(n):
        ts = start_ts + dt.timedelta(minutes=5 * i)
        o = price
        c = price - step
        rows.append(_bar(ts, o, max(o, c) + 0.05, min(o, c) - 0.05, c))
        price = c
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def test_enters_in_a_clean_uptrend_above_vwap():
    df = _uptrend_df()
    result = main.add_strategy_signal(df, "heikin_ashi_vwap", {"require_no_lower_wick": False})
    assert result["long"].any()


def test_never_enters_in_a_downtrend_below_vwap():
    df = _downtrend_df()
    result = main.add_strategy_signal(df, "heikin_ashi_vwap", {"require_no_lower_wick": False})
    assert not result["long"].any()


def test_no_lower_wick_filter_never_adds_entries_only_removes_them():
    df = _uptrend_df()
    loose = main.add_strategy_signal(df.copy(), "heikin_ashi_vwap", {"require_no_lower_wick": False})
    strict = main.add_strategy_signal(df.copy(), "heikin_ashi_vwap", {"require_no_lower_wick": True})
    loose_long = set(loose.index[loose["long"]])
    strict_long = set(strict.index[strict["long"]])
    assert strict_long <= loose_long


def test_handles_short_dataframe_without_raising():
    df = _uptrend_df(n=2)
    result = main.add_strategy_signal(df, "heikin_ashi_vwap", {"require_no_lower_wick": False})
    assert len(result) <= 2  # never crashes, degrades gracefully
