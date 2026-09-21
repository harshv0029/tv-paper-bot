"""Tests for the sweep_engulf_retracement_v1 strategy (2026-09-21, adapted
from a social-media strategy post - Instagram, @OmarAgag6 - per explicit
user request). Scoped down to this file's single-timeframe/single-boolean-
column architecture, same as every other strategy here: stop/target/sizing
math is baked into this strategy's own "long" column (unlike most other
strategies, which leave stop/target entirely to the caller) because the
source strategy's stop-loss (sweep-zone low) and fixed 2:1 target are
central to what's being tested, but position sizing/order placement is
still entirely the caller's job.

Fixture layout (indices 0-based, 15-minute bars, sweep_htf_minutes=60 so
each HTF bucket is exactly 4 base bars - keeps fixtures small):
  Bucket A (bars 0-3):  a bearish HTF candle, Open=110, Close=100, Low=98.
  Bucket B (bars 4-7):  a bullish engulfing candle that both engulfs
                        bucket A's body AND sweeps its low (Low=90 < 98) -
                        the signal bucket. Zone = [(High+Low)/2, Low] =
                        [107.5, 90].
  Bucket C (bars 8-11): the zone is active from bar 8 onward (bucket B
                        just closed). Price pulls back into the zone,
                        forming a local swing high at bar 9 (High=113)
                        that isn't broken again until bucket D.
  Bucket D (bars 12+):  bar 12 closes at 114, above the bar-9 swing high
                        (113) - break-of-structure entry fires here.
                        Stop=90 (zone low), target=114+2*(114-90)=162.
"""
import pandas as pd

import main


def _bar(o, h, l, c, v=100.0):
    return {"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}


def _bucket_a():
    return [
        _bar(110, 112, 108, 109),
        _bar(109, 110, 105, 106),
        _bar(106, 107, 98, 99),
        _bar(99, 100, 98, 100),
    ]


def _bucket_b_signal():
    # Engulfs bucket A (Open=99<=100, Close=120>=110) AND sweeps its low
    # (Low=90 < 98).
    return [
        _bar(99, 100, 90, 95),
        _bar(95, 105, 94, 100),
        _bar(100, 115, 99, 110),
        _bar(110, 125, 108, 120),
    ]


def _bucket_b_no_sweep():
    # Same engulfing shape, but never trades below bucket A's low (98) -
    # engulfs without sweeping.
    return [
        _bar(99, 100, 99, 100),
        _bar(100, 105, 99, 101),
        _bar(101, 115, 100, 110),
        _bar(110, 125, 109, 120),
    ]


def _rows_to_df(rows, start="2026-01-05 08:00"):
    dates = pd.date_range(start, periods=len(rows), freq="15min", tz="Asia/Kolkata")
    cols = {k: [r[k] for r in rows] for k in ("Open", "High", "Low", "Close", "Volume")}
    return pd.DataFrame({"Date": dates, **cols})


def test_engulfing_without_a_sweep_never_opens_a_zone():
    rows = _bucket_a() + _bucket_b_no_sweep() + [
        _bar(118, 119, 90, 95),  # would touch a [107.5,90]-style zone if one existed
        _bar(95, 96, 85, 90),
    ]
    out = main.add_strategy_signal(_rows_to_df(rows), "sweep_engulf_retracement_v1", {"htf_minutes": 60})
    assert out["long"].tolist() == [False] * len(out)
    assert out["sweep_zone_top"].isna().all()


def test_full_setup_enters_on_structure_break_with_correct_stop_and_zone():
    rows = _bucket_a() + _bucket_b_signal() + [
        _bar(118, 119, 110, 112),  # bar8: above zone (107.5), no touch yet
        _bar(112, 113, 105, 106),  # bar9: touches zone, sets swing_high=113
        _bar(106, 108, 100, 102),  # bar10: no break, swing_high stays 113
        _bar(102, 104, 95, 98),    # bar11: no break, swing_high stays 113
        _bar(98, 115, 97, 114),    # bar12: closes 114 > 113 -> entry
    ]
    out = main.add_strategy_signal(_rows_to_df(rows), "sweep_engulf_retracement_v1", {"htf_minutes": 60})
    assert out["long"].tolist() == [False] * 12 + [True]
    assert out.loc[12, "sweep_zone_top"] == 107.5
    assert out.loc[12, "sweep_zone_bottom"] == 90.0


def test_target_hit_exits_at_two_to_one_and_stop_hit_exits_at_the_zone_low():
    rows = _bucket_a() + _bucket_b_signal() + [
        _bar(118, 119, 110, 112),
        _bar(112, 113, 105, 106),
        _bar(106, 108, 100, 102),
        _bar(102, 104, 95, 98),
        _bar(98, 115, 97, 114),    # bar12: entry at close=114, stop=90, target=114+2*24=162
        _bar(114, 130, 113, 125),  # bar13: still holding
        _bar(125, 165, 124, 163),  # bar14: close=163 >= target(162) -> exit
    ]
    out = main.add_strategy_signal(_rows_to_df(rows), "sweep_engulf_retracement_v1", {"htf_minutes": 60})
    assert out["long"].tolist() == [False] * 12 + [True, True, False]


def test_price_breaking_the_zone_low_before_entry_invalidates_the_setup():
    rows = _bucket_a() + _bucket_b_signal() + [
        _bar(118, 119, 110, 112),  # touches nothing yet
        _bar(112, 113, 105, 106),  # touches zone, swing_high=113
        _bar(106, 108, 85, 80),    # closes at 80, below zone_bottom (90) -> invalidated
        _bar(80, 120, 79, 115),    # even though this closes above the old swing_high, no zone left -> no entry
    ]
    out = main.add_strategy_signal(_rows_to_df(rows), "sweep_engulf_retracement_v1", {"htf_minutes": 60})
    assert out["long"].tolist() == [False] * len(out)
