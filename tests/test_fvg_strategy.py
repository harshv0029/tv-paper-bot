"""Tests for the fair_value_gap strategy (2026-09-21, explicit user
instruction: "Implement this strategy and get this backtesting done" -
pasted a full multi-factor Smart Money Concepts spec). Scoped down to this
file's single-timeframe/single-boolean-column architecture (see main.py's
own comment on the "fair_value_gap" elif branch for the scope-reduction
rationale) - stop/target/sizing stays the caller's job, same as every
other strategy here.

Fixture layout shared by every test below (indices 0-based):
  0-18  (19 bars): flat baseline - Open=Close=100, High=101, Low=99,
        Volume=100. Warms up both the 14-bar ATR and the 20-bar volume
        average so bar 19's own values land exactly on the boundary where
        those rolling windows first become non-NaN.
  18    is candle A (High=101) - two bars before candle C at 20.
  19    is candle B (the displacement candle) - overridden per test.
  20    is candle C (the gap candle) - Low=112, well above A's High=101,
        so a gap always exists geometrically; each test controls whether
        the displacement/volume FILTERS let it count as a real FVG.
  21+   appended per test to exercise retrace-entry / expiry / exit.
"""
import pandas as pd

import main


def _base_rows(n=19):
    return {
        "Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
        "Close": [100.0] * n, "Volume": [100.0] * n,
    }


def _fixture(b_row, c_row, extra_rows=None):
    rows = _base_rows()
    for col, val in b_row.items():
        rows[col].append(val)
    for col in rows:
        if col not in b_row:
            rows[col].append({"Open": 100.0, "High": 101.0, "Low": 99.0,
                               "Close": 100.0, "Volume": 100.0}[col])
    for col, val in c_row.items():
        rows[col].append(val)
    for col in rows:
        if col not in c_row and len(rows[col]) == 19:
            rows[col].append({"Open": 112.0, "High": 120.0, "Low": 112.0,
                               "Close": 118.0, "Volume": 100.0}[col])
    for extra in (extra_rows or []):
        for col, val in extra.items():
            rows[col].append(val)
    n = len(rows["Open"])
    dates = pd.date_range("2026-01-05 09:15", periods=n, freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame({"Date": dates, **rows})


STRONG_B = {"Open": 100.0, "High": 110.0, "Low": 100.0, "Close": 110.0, "Volume": 500.0}
STRONG_C = {"Open": 112.0, "High": 120.0, "Low": 112.0, "Close": 118.0, "Volume": 100.0}
WEAK_BODY_B = {"Open": 100.0, "High": 102.0, "Low": 100.0, "Close": 102.0, "Volume": 500.0}
WEAK_VOL_B = {"Open": 100.0, "High": 110.0, "Low": 100.0, "Close": 110.0, "Volume": 100.0}


def test_clean_bullish_fvg_detected_and_diagnostic_columns_set():
    df = _fixture(STRONG_B, STRONG_C)
    out = main.add_strategy_signal(df, "fair_value_gap", {})
    # zone = [High(A)=101, Low(C)=112]; bar 20 itself never enters long
    # (the zone was only just created, price is still above it).
    assert out.loc[20, "long"] == False
    assert out.loc[20, "fvg_top"] == 112.0
    assert out.loc[20, "fvg_bottom"] == 101.0


def test_displacement_filter_rejects_a_weak_gap():
    # Same geometric gap (Low[20]=112 > High[18]=101) and elevated volume,
    # but B's body (2) is far below its own ATR*1.5 (~3.86) - must never
    # count as a tradeable FVG, so long stays False even on a later
    # retrace into where the (non-existent) zone would have been.
    df = _fixture(WEAK_BODY_B, STRONG_C, extra_rows=[
        {"Open": 108.0, "High": 111.0, "Low": 105.0, "Close": 108.0, "Volume": 100.0},
    ])
    out = main.add_strategy_signal(df, "fair_value_gap", {})
    assert out["long"].tolist() == [False] * len(out)


def test_volume_filter_rejects_a_low_volume_gap():
    # Same strong-body displacement candle, but its volume (100) never
    # clears its own 20-bar average * 1.5 - must never count as a
    # tradeable FVG.
    df = _fixture(WEAK_VOL_B, STRONG_C, extra_rows=[
        {"Open": 108.0, "High": 111.0, "Low": 105.0, "Close": 108.0, "Volume": 100.0},
    ])
    out = main.add_strategy_signal(df, "fair_value_gap", {})
    assert out["long"].tolist() == [False] * len(out)


def test_entry_fires_only_on_retrace_to_fifty_percent_equilibrium():
    # zone top=112, bottom=101 -> equilibrium=106.5. Bar 21's Low=107
    # stays above equilibrium (no entry yet); bar 22's Low=106 reaches it
    # (entry fires at bar 22, the same bar the retrace happens).
    df = _fixture(STRONG_B, STRONG_C, extra_rows=[
        {"Open": 111.0, "High": 113.0, "Low": 107.0, "Close": 111.0, "Volume": 100.0},
        {"Open": 108.0, "High": 109.0, "Low": 106.0, "Close": 108.0, "Volume": 100.0},
    ])
    out = main.add_strategy_signal(df, "fair_value_gap", {})
    assert out["long"].tolist() == [False] * 22 + [True]


def test_exit_fires_on_close_back_below_the_zone_bottom():
    # Continues the entry fixture above (entry fires at bar 22): bar 23
    # closes at 95, below the zone's own bottom (101) - structural
    # invalidation, exit.
    df = _fixture(STRONG_B, STRONG_C, extra_rows=[
        {"Open": 111.0, "High": 113.0, "Low": 107.0, "Close": 111.0, "Volume": 100.0},
        {"Open": 108.0, "High": 109.0, "Low": 106.0, "Close": 108.0, "Volume": 100.0},
        {"Open": 100.0, "High": 101.0, "Low": 94.0, "Close": 95.0, "Volume": 100.0},
    ])
    out = main.add_strategy_signal(df, "fair_value_gap", {})
    assert out["long"].tolist() == [False] * 22 + [True, False]


def test_stale_unfilled_fvg_expires_and_stops_being_tradeable():
    # fvg_expiry_bars=2: the zone created at bar 20 must expire by the
    # time bar 23 arrives (3 bars later) even though bar 23's Low finally
    # reaches the equilibrium level - expiry must win, no late entry.
    df = _fixture(STRONG_B, STRONG_C, extra_rows=[
        {"Open": 115.0, "High": 116.0, "Low": 113.0, "Close": 115.0, "Volume": 100.0},
        {"Open": 114.0, "High": 115.0, "Low": 112.0, "Close": 114.0, "Volume": 100.0},
        {"Open": 108.0, "High": 109.0, "Low": 106.0, "Close": 108.0, "Volume": 100.0},
    ])
    out = main.add_strategy_signal(df, "fair_value_gap", {"fvg_expiry_bars": 2})
    assert out["long"].tolist() == [False] * len(out)
