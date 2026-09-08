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
# Hard ceiling on live entries, independent of TTL (2026-09-08, Render's
# own "exceeded its memory limit" alert - a SECOND OOM after the
# 2026-09-07 fix below, root-caused differently: TTL pruning only removes
# entries that have gone STALE, so at ~2,661 symbols the cache can still
# legitimately hold up to ~2,661 live DataFrames at once if a full
# round-robin sweep completes inside one TTL window - not unbounded
# growth over time, but a real worst-case working set the TTL alone
# doesn't cap. This forces a hard ceiling regardless of TTL timing: once
# over the cap, evict the OLDEST entries first (same "expired-first"
# spirit as the TTL prune) until back under it. ~400 covers the biggest
# batch this app draws in one go (SCHEDULER_ENTRY_SCAN_BATCH_SIZE, plus
# open positions, plus interactive chart/backtest calls) with headroom,
# without still holding a stale-but-not-yet-expired copy of the entire
# watchlist.
_MAX_CACHE_ENTRIES = 400


def fetch_ohlc(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Fetches OHLC data, cached briefly in memory so a sweep of many strategy
    params against the same symbol/period/interval only hits Yahoo Finance once,
    not once per combination.

    2026-09-07: also prunes any cache entry past its TTL on every call.
    Found live as the root cause of a Render OOM crash (Render's own email
    alert; "all live trades vanished with all closed trades too" on the
    restart that followed) - _DATA_CACHE entries were NEVER removed, only
    ever overwritten by a fresh fetch of the exact same key. A stale entry
    was already useless (the TTL check above never returns it as a hit),
    it just wasn't being freed - so the dict grew for the entire life of
    the process. Harmless at the old ~103-symbol watchlist; got much worse
    once WATCHLIST grew to ~2,644 symbols (2026-09-05/07) - a single
    round-robin rotation alone now touches every one of them, each
    leaving behind a DataFrame that would otherwise sit in memory forever."""
    key = (symbol, period, interval)
    now = time.time()

    cached = _DATA_CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1].copy()

    # Prune everything past its TTL before adding a new entry - keeps
    # _DATA_CACHE bounded to roughly "what's been fetched in the last TTL
    # window," not "everything ever fetched since the process started."
    expired_keys = [k for k, (ts, _) in _DATA_CACHE.items() if (now - ts) >= _CACHE_TTL_SECONDS]
    for k in expired_keys:
        del _DATA_CACHE[k]

    # Hard cap, on top of the TTL prune above (2026-09-08) - see
    # _MAX_CACHE_ENTRIES' own comment for why TTL pruning alone isn't
    # enough at this watchlist size. Oldest-first eviction, same as a
    # simple LRU by insertion time.
    if len(_DATA_CACHE) >= _MAX_CACHE_ENTRIES:
        oldest_keys = sorted(_DATA_CACHE, key=lambda k: _DATA_CACHE[k][0])
        for k in oldest_keys[: len(_DATA_CACHE) - _MAX_CACHE_ENTRIES + 1]:
            del _DATA_CACHE[k]

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
