"""
Market-data fetch + short in-memory caching (yfinance-backed).

Extracted from main.py as part of the docs/PROJECT_STRUCTURE_PLAN.md Phase 1
module split - pure code motion (bodies/docstrings unchanged from their
original main.py definitions), not a logic change.
"""
import time

import pandas as pd
import yfinance as yf
from fastapi import HTTPException

_DATA_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 180  # re-fetch at most every 3 minutes per (symbol, period, interval)


def fetch_ohlc(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Fetches OHLC data, cached briefly in memory so a sweep of many strategy
    params against the same symbol/period/interval only hits Yahoo Finance once,
    not once per combination."""
    key = (symbol, period, interval)
    now = time.time()

    cached = _DATA_CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1].copy()

    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No data for symbol={symbol!r} period={period!r} interval={interval!r}.",
        )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"
    df = df.rename(columns={date_col: "Date"}).dropna(subset=["Open", "High", "Low", "Close"])
    df = df.reset_index(drop=True)

    _DATA_CACHE[key] = (now, df)
    return df.copy()


def get_fx_to_inr(currency: str) -> float:
    """1 unit of `currency` -> this many INR. Live rate (cached like any
    other fetch_ohlc call), not a hardcoded guess - USD/INR moves enough
    that a stale constant would itself become a sizing error."""
    if currency == "INR":
        return 1.0
    if currency == "USD":
        df = fetch_ohlc("INR=X", "5d", "1d")
        return float(df["Close"].iloc[-1])
    raise HTTPException(status_code=400, detail=f"No FX rate wired up for currency={currency!r}")
