"""Tests for primary_base_entry_signal (2026-10-01), per
docs/minervini_book_notes.txt's CHAPTER 11 "PRIMARY BASE" note: a recently-
listed stock (proxy: short overall available history) breaking out to a new
ALL-TIME HIGH from its first buyable base. Covers:
  - too-much-history guard (the "recently listed" proxy's own ceiling)
  - base-duration guard (too young / too old)
  - the two-tier depth cap (short base <=35%, long base <=50%)
  - the breakout-above-all-time-high condition
  - the volume-surge requirement on the breakout bar
  - entry_price/stop_loss/atr_at_entry shape on a valid fire
Fixtures are built programmatically: a flat low-volume lead-in, one
all-time-high bar (High=100), a base_days-long decline/base reaching a
precise depth_pct below that high, then a final (evaluated) bar - the same
"evaluates only the last row" convention every other entry-signal function
in this file uses."""
import pandas as pd
import pytest

import main


def _fixture(base_days, depth_pct, lead_in=10, extra_lead_in=0, breakout=True, vol_surge=True):
    ath = 100.0
    base_low = ath * (1 - depth_pct / 100.0)

    rows = []
    for _ in range(lead_in + extra_lead_in):
        rows.append({"Close": 50.0, "High": 50.5, "Low": 49.5, "Volume": 1000.0})
    rows.append({"Close": 99.0, "High": ath, "Low": 98.0, "Volume": 1200.0})  # all-time-high bar

    n_mid = base_days - 1
    if n_mid > 0:
        rows.append({"Close": base_low + 1.0, "High": base_low + 1.5, "Low": base_low, "Volume": 1000.0})
        for _ in range(n_mid - 1):
            rows.append({"Close": base_low + 2.0, "High": base_low + 2.5, "Low": base_low + 1.0, "Volume": 1000.0})

    if breakout:
        final = {"Close": ath + 5.0, "High": ath + 6.0, "Low": ath + 3.0}
    else:
        final = {"Close": ath - 5.0, "High": ath - 4.0, "Low": ath - 8.0}
    final["Volume"] = 3000.0 if vol_surge else 1200.0
    rows.append(final)

    df = pd.DataFrame(rows)
    df["Date"] = pd.date_range("2024-01-01", periods=len(df)).astype(str)
    return df


def test_no_signal_when_total_history_exceeds_the_recently_listed_proxy_ceiling():
    df = _fixture(base_days=18, depth_pct=20.0, extra_lead_in=750)
    assert len(df) > main.MINERVINI_PRIMARY_BASE_MAX_HISTORY_DAYS
    assert main.primary_base_entry_signal(df) is None


def test_no_signal_when_base_is_younger_than_the_minimum_duration():
    df = _fixture(base_days=10, depth_pct=20.0)  # < MINERVINI_PRIMARY_BASE_MIN_BASE_DAYS (15)
    assert main.primary_base_entry_signal(df) is None


def test_no_signal_when_base_is_older_than_the_maximum_duration():
    df = _fixture(base_days=300, depth_pct=20.0)  # > MINERVINI_PRIMARY_BASE_MAX_BASE_DAYS (252)
    assert main.primary_base_entry_signal(df) is None


def test_short_base_within_depth_cap_fires():
    df = _fixture(base_days=18, depth_pct=20.0)  # <= SHORT_BASE_MAX_DAYS(25), <= SHORT_MAX_DEPTH_PCT(35)
    sig = main.primary_base_entry_signal(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] == 80.0  # 100 * (1 - 0.20)
    assert sig["atr_at_entry"] > 0


def test_short_base_exceeding_depth_cap_is_rejected():
    df = _fixture(base_days=18, depth_pct=40.0)  # short-tier duration but 40% > SHORT_MAX_DEPTH_PCT(35)
    assert main.primary_base_entry_signal(df) is None


def test_long_base_within_its_own_wider_depth_cap_fires():
    df = _fixture(base_days=100, depth_pct=45.0)  # long-tier, <= LONG_MAX_DEPTH_PCT(50)
    sig = main.primary_base_entry_signal(df)
    assert sig is not None
    assert sig["stop_loss"] == pytest.approx(55.0)  # 100 * (1 - 0.45)


def test_long_base_exceeding_even_the_wider_depth_cap_is_rejected():
    df = _fixture(base_days=100, depth_pct=55.0)  # > LONG_MAX_DEPTH_PCT(50)
    assert main.primary_base_entry_signal(df) is None


def test_no_signal_without_a_genuine_breakout_above_the_all_time_high():
    df = _fixture(base_days=18, depth_pct=20.0, breakout=False)
    assert main.primary_base_entry_signal(df) is None


def test_no_signal_without_a_volume_surge_on_the_breakout_bar():
    df = _fixture(base_days=18, depth_pct=20.0, breakout=True, vol_surge=False)
    assert main.primary_base_entry_signal(df) is None
