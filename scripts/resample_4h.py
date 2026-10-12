"""Reusable 1h -> 4h resample helper for research scripts (backlog: 4h candle owed).

yfinance has no 4h interval, so 4h bars are built from 1h bars. NSE session-aware: a naive
`resample("4h")` would cut on clock hours (00:00, 04:00, ...) and glue the 09:15 open to bars that
do not belong together. Instead each trading DAY is split into session buckets anchored at the
09:15 IST open, one bucket per 4 hours:
  bucket 0: 09:15 <= t < 13:15  (1h bars starting 09:15, 10:15, 11:15, 12:15 -> a full 4h bar)
  bucket 1: 13:15 <= t < 17:15  (bars 13:15, 14:15, 15:15 -> a SHORT 3h bar ending at the 15:30 close)
Bars never span two days, so the overnight gap stays between bars (the next day's open is its own
bar open). The stamp of each 4h bar is the start of its first 1h bar. OHLCV: first open, max high,
min low, last close, summed volume. Bar counts differ from 4h-of-clock-time: 2 bars/day, with
average bar length 3.5 h (use BAR_HOURS_4H for hours-held maths); stated, not hidden.
Bar-count constants (holds, lookbacks) change meaning at 4h: a 5-bar hold is 2.5 days, not 5 hours.
For non-NSE sessions pass `session_open_minute` (minutes after midnight in the index's own tz).
"""
import numpy as np
import pandas as pd

NSE_OPEN_MINUTE = 9 * 60 + 15
BAR_HOURS_4H = 3.5      # (4h + 3h) / 2 average real hours per NSE 4h bar
BARS_PER_DAY_4H = 2


def resample_1h_to_4h(df, session_open_minute=NSE_OPEN_MINUTE, bucket_minutes=240):
    """Resample a 1h OHLCV frame (DatetimeIndex, tz-aware or naive, local exchange time) to session-anchored 4h bars."""
    if df is None or len(df) == 0:
        return df
    idx = pd.DatetimeIndex(df.index)
    mod = np.asarray(idx.hour * 60 + idx.minute)
    bucket = np.maximum(0, (mod - session_open_minute) // bucket_minutes)
    day = np.asarray(idx.normalize().asi8)
    keys = [day, bucket]
    g = df.groupby(keys, sort=True)
    agg = {"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(), "Close": g["Close"].last()}
    if "Volume" in df.columns:
        agg["Volume"] = g["Volume"].sum()
    out = pd.DataFrame(agg)
    first_ts = pd.Series(idx, index=df.index).groupby(keys, sort=True).first()
    out.index = pd.DatetimeIndex(first_ts.tolist())
    return out.sort_index()
