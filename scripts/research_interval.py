"""Shared interval/period handling for research scripts (B-842, B-588, B-743 dispatch readiness).

yfinance history caps: 1m 7d, 5m/15m 60d, 1h 730d. 4h is not a yfinance interval: it is fetched as 1h
and resampled with scripts/resample_4h.py (NSE session-anchored). Bar-count constants change meaning
with the interval (a 30-bar hold is 30 days at 1d, about 15 days at 4h, 30 hours at 1h).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resample_4h import resample_1h_to_4h  # noqa: E402

INTERVALS = ("1d", "4h", "1h", "15m", "5m", "1m")
DEFAULT_PERIOD = {"1d": "5y", "4h": "730d", "1h": "730d", "15m": "60d", "5m": "60d", "1m": "7d"}
MAX_DAYS = {"1m": 7, "5m": 60, "15m": 60, "1h": 730, "4h": 730}
FETCH = {"4h": "1h"}


def _days(period):
    p = str(period or "").strip().lower()
    try:
        if p.endswith("mo"):
            return int(p[:-2]) * 30
        if p.endswith("d"):
            return int(p[:-1])
        if p.endswith("y"):
            return int(p[:-1]) * 365
    except ValueError:
        return None
    return None


def cap_period(interval, period):
    """Return a period valid for the interval: default when blank, clamped to the yfinance cap."""
    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval {interval}")
    if not str(period or "").strip():
        return DEFAULT_PERIOD[interval]
    cap = MAX_DAYS.get(interval)
    d = _days(period)
    if cap is not None and (d is None or d > cap):
        return DEFAULT_PERIOD[interval]
    return period


def fetch_interval(m, sym, period, interval):
    """m.fetch_ohlc honouring the cap; 4h = 1h bars resampled to 09:15-anchored 4h bars."""
    period = cap_period(interval, period)
    raw = m.fetch_ohlc(sym, period, FETCH.get(interval, interval))
    if interval == "4h" and raw is not None and len(raw):
        raw = resample_1h_to_4h(raw)
    return raw
