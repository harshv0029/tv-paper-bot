"""Tests for the early-session "no signal in the first hour" fix
(2026-09-09, explicit user finding: "what you need to start entering
into trade in early mornings like 9:30 or 9:40 because u don't detect
any signal in first one hour of market open while most traders do that
early trade"). Root cause: _auto_signal_core's own trend/SMA/confidence
read was computed from TODAY-ONLY closes (today_df), so on 5-minute live
bars sma_f needed sma_fast bars INTO TODAY to exist at all (45 min for
the default sma_fast=9), sma_s needed sma_slow bars (105 min for
sma_slow=21, up to ~4h10m for the sma_slow=50 symbols), and
_trend_confidence needed sma_slow+2 bars before it could return anything
above its own 0.0 floor - mathematically impossible for the first
1-4+ hours of every session regardless of how strong the actual move
was. Fixed by reading closes from the full multi-day `df` instead (same
precedent _volume_confirms already used) - orb_high/orb_low/last_close
(the actual ORB definition) stay strictly today-only, unchanged.
Same fix applied to _compute_trend (the options overlay's own trend
read), which had the identical bug."""
import datetime as real_datetime
import math
import os
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


class _FixedUtcNow(real_datetime.datetime):
    """Subclasses real datetime.datetime so dt.timedelta/other datetime
    machinery main.py uses elsewhere keeps working unchanged - only
    utcnow() itself is pinned."""
    _fixed = real_datetime.datetime(2026, 9, 9, 4, 5, 0)  # UTC -> 09:35 IST

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _multi_day_fixture(today_bars: int = 5):
    """4 full prior days (20 bars each, 100 total) + `today_bars` bars of
    today, all 5-minute UTC timestamps landing at 09:15 IST onward
    (03:45 UTC = 09:15 IST, IST_OFFSET_MIN=330). A smooth-but-noisy
    uptrend (close = 100 + 0.15*i + 0.3*sin(i/2)) across the WHOLE
    85-bar series - realistic enough for _trend_confidence to read a
    real, non-zero signal once it can see the prior days, impossible for
    it to read at all from only `today_bars` bars alone (5 < the
    sma_fast=9 default)."""
    prior_days = ["2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"]
    bars_per_prior_day = 20
    rows = []
    i = 0
    for day in prior_days:
        base = pd.Timestamp(f"{day} 03:45:00")  # UTC, -> 09:15 IST
        for b in range(bars_per_prior_day):
            ts = base + pd.Timedelta(minutes=5 * b)
            close = 100 + 0.15 * i + 0.3 * math.sin(i / 2.0)
            rows.append({
                "Date": ts, "Open": close, "High": close + 0.2, "Low": close - 0.2,
                "Close": close, "Volume": 1000 + (i % 10) * 10,
            })
            i += 1
    base_today = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
    for b in range(today_bars):
        ts = base_today + pd.Timedelta(minutes=5 * b)
        close = 100 + 0.15 * i + 0.3 * math.sin(i / 2.0)
        rows.append({
            "Date": ts, "Open": close, "High": close + 0.2, "Low": close - 0.2,
            "Close": close, "Volume": 1000 + (i % 10) * 10,
        })
        i += 1
    return pd.DataFrame(rows)


def test_auto_signal_core_computes_trend_within_first_hour_using_multi_day_closes():
    _fresh_db()
    fixture = _multi_day_fixture(today_bars=5)  # only 20 min into today (9:15-9:35)
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture):
        result = main._auto_signal_core("TESTSTOCK.NS", currency="INR")

    assert result["status"] == "checked", f"expected a real check, got {result}"
    # The core of the fix: with only 5 bars into today (< sma_fast=9), the
    # OLD today_df-only closes made sma_f/sma_s/trend impossible - None,
    # None, None - no matter how strong the actual multi-day trend was.
    assert result["sma_fast"] is not None, "sma_fast must be computable within the first hour using prior-day bars"
    assert result["sma_slow"] is not None, "sma_slow must be computable within the first hour using prior-day bars"
    assert result["trend"] == "up", "the fixture's own smooth uptrend must read through"


def test_auto_signal_core_todays_own_closes_alone_could_not_have_done_this():
    """Sanity check the OLD bug is real, not a strawman - reproduces
    exactly what today_df-only closes would have seen: with only 5 bars
    today (< sma_fast=9), sma_f/sma_s can't be computed from today's
    closes alone, and _trend_confidence's own floor requires n >=
    sma_slow+2 (23 for the default sma_slow=21)."""
    fixture = _multi_day_fixture(today_bars=5)
    today_only_closes = fixture[fixture["Date"] >= pd.Timestamp("2026-09-09 03:45:00")]["Close"].to_numpy()
    assert len(today_only_closes) == 5
    assert len(today_only_closes) < 9  # sma_fast default - sma_f would have been None
    assert main._trend_confidence(today_only_closes, 9, 21) == 0.0, \
        "today-only closes must fail _trend_confidence's own not-enough-history floor"
    # ...but the fix's full multi-day closes read a real, non-zero signal
    # from the exact same moment in the session:
    full_closes = fixture["Close"].to_numpy()
    assert main._trend_confidence(full_closes, 9, 21) > 0.0


def test_compute_trend_also_computes_within_first_hour_using_multi_day_closes():
    fixture = _multi_day_fixture(today_bars=5)
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture):
        direction, confidence = main._compute_trend("TESTSTOCK.NS", 9, 21, main.IST_OFFSET_MIN)

    assert direction == "up"
    assert confidence > 0.0, "the options overlay's own trend read must also see the prior-day bars"


def test_auto_signal_core_orb_high_low_remain_today_only_unaffected_by_the_fix():
    """The fix must NOT leak prior-day highs/lows into the opening range
    itself - orb_high/orb_low are still computed from the ORB window's
    own today-only bars, exactly as before."""
    _fresh_db()
    fixture = _multi_day_fixture(today_bars=5)
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture):
        result = main._auto_signal_core("TESTSTOCK.NS", currency="INR")

    today_only = fixture[fixture["Date"] >= pd.Timestamp("2026-09-09 03:45:00")]
    orb_window = today_only[today_only["Date"] < pd.Timestamp("2026-09-09 03:45:00") + pd.Timedelta(minutes=15)]
    assert result["orb_high"] == pytest.approx(float(orb_window["High"].max()))
    assert result["orb_low"] == pytest.approx(float(orb_window["Low"].min()))
