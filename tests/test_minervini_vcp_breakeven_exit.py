"""Tests for minervini_vcp_exit_reason_breakeven (2026-09-29, explicit user
instruction: build a 2R/3R move-to-breakeven exit variant, book-literal per
docs/minervini_book_notes.txt chapter 13 - a straight ALTERNATIVE to the
existing minervini_vcp_exit_reason ATR chandelier trail, NOT a hybrid of the
two: "move the stop to breakeven, full stop - not a trailing/chandelier
mechanism"). Covers:
  - the stop stays flat at initial_stop (no ATR trailing at all) until the
    breakeven_r_multiple threshold is crossed,
  - the stop floors at breakeven once 2R is reached and never reverts,
  - the stop floors at breakeven once 3R is reached (separate fixture,
    same family, different breakeven_r_multiple),
  - the flat pre-threshold stop is genuinely flat, not the chandelier trail
    in disguise (a large adverse move that would trip the chandelier trail
    but not the flat initial_stop must NOT exit).
Fixtures are hand-engineered close/date arrays fed bar-by-bar, the same
convention test_minervini_vcp.py's own exit-reason tests use (the function
evaluates only the last row of `df` each call; the caller threads
running_max_close forward)."""
import numpy as np
import pandas as pd

import main


def _sub_df(close: np.ndarray, dates: np.ndarray, i: int) -> pd.DataFrame:
    return pd.DataFrame({"Close": close[: i + 1], "Date": dates[: i + 1]})


# ---- stop stays flat at initial_stop until the R-threshold is crossed -------

def test_stop_stays_flat_at_initial_stop_below_the_r_threshold():
    # entry_price=100, initial_stop=80 => initial risk R=20, so 2R=40
    # (threshold at running peak 140). The peak here only reaches 120
    # (gain=20=1R), well under the 2R threshold, so the stop must stay
    # flat at initial_stop (80) the whole time - never trailing up with
    # price the way the chandelier variant would.
    close = np.array([100.0, 110.0, 120.0, 115.0, 105.0, 95.0, 85.0, 81.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 80.0
    atr_at_entry = 3.0  # deliberately small; must be irrelevant to this variant

    running_max = entry_price
    reason = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason, running_max = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max,
            entry_price, main.MINERVINI_BREAKEVEN_R_2,
        )
        if reason:
            break
    # A chandelier trail (peak 120, ATR 3, mult 2 => trail 114) would have
    # exited back at close=105 already; the flat 2R variant must not exit
    # until price actually reaches down to the flat initial_stop of 80.
    assert reason is None
    assert close[-1] > initial_stop  # fixture never actually reaches 80 yet

    # One more bar down through initial_stop must now exit, confirming the
    # flat stop is live (not simply "never exits").
    close2 = np.append(close, 79.0)
    dates2 = np.append(dates, pd.Timestamp("2026-01-09").strftime("%Y-%m-%d"))
    sub2 = _sub_df(close2, dates2, len(close2) - 1)
    reason2, _ = main.minervini_vcp_exit_reason_breakeven(
        sub2, entry_day, initial_stop, atr_at_entry, running_max,
        entry_price, main.MINERVINI_BREAKEVEN_R_2,
    )
    assert reason2 == "stop_hit"


def test_large_adverse_move_that_would_trip_a_chandelier_trail_does_not_exit_pre_threshold():
    # Peak close of 110 with a small ATR would make a chandelier trail
    # exit almost immediately on any pullback. This variant has NO ATR
    # component pre-threshold: with initial_stop=80, a pullback to 90 must
    # NOT exit, proving the stop is genuinely flat, not the chandelier
    # trail relabeled.
    close = np.array([100.0, 110.0, 90.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 80.0
    atr_at_entry = 2.0  # chandelier (mult=2) would trail to 110-4=106, well above 90

    running_max = entry_price
    reason = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason, running_max = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max,
            entry_price, main.MINERVINI_BREAKEVEN_R_2,
        )
    assert reason is None


# ---- stop floors at breakeven once 2R is reached, and never reverts ---------

def test_stop_floors_at_breakeven_once_2r_reached_and_never_reverts():
    # entry_price=100, initial_stop=95 => R=5, so 2R=10 (peak >= 110).
    close = np.array([100.0, 105.0, 110.0, 108.0, 101.0, 99.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 95.0
    atr_at_entry = 1.0  # irrelevant to this variant; kept small on purpose

    running_max = entry_price
    reason = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason, running_max = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max,
            entry_price, main.MINERVINI_BREAKEVEN_R_2,
        )
        if reason:
            break
    # Peak of 110 (gain=10=2R) moves the stop to breakeven (100). The
    # pullback to 99 breaches that floor and exits - note this is BELOW
    # initial_stop's own level of 95 would never trigger; it's specifically
    # the breakeven floor (100) doing the work here since 99 > 95.
    assert reason == "stop_hit"
    assert 99.0 < entry_price  # confirms exit was via the breakeven floor, not initial_stop
    assert 99.0 > initial_stop


def test_breakeven_floor_never_reverts_even_on_a_deep_pullback_before_the_final_bar():
    # Once breakeven is earned it must stay earned even through an
    # intervening bar that doesn't itself breach the floor - running_max
    # only ratchets up, so re-evaluating the trigger condition on a later
    # (lower) running_max never un-triggers it.
    close = np.array([100.0, 112.0, 101.0, 99.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 95.0  # R=5, 2R=10, peak of 112 clears it (gain=12)
    atr_at_entry = 1.0

    running_max = entry_price
    reason = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason, running_max = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max,
            entry_price, main.MINERVINI_BREAKEVEN_R_2,
        )
        if i == 2:
            # At close=101, still above breakeven (100) - must not exit,
            # and the floor must already be armed (not just "about to be").
            assert reason is None
    assert reason == "stop_hit"  # close=99 breaches the now-permanent breakeven floor


# ---- stop floors at breakeven once 3R is reached -----------------------------

def test_stop_floors_at_breakeven_once_3r_reached():
    # entry_price=100, initial_stop=94 => R=6, so 3R=18 (peak >= 118).
    close = np.array([100.0, 110.0, 118.0, 115.0, 99.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 94.0
    atr_at_entry = 1.0

    running_max = entry_price
    reason = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason, running_max = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max,
            entry_price, main.MINERVINI_BREAKEVEN_R_3,
        )
        if reason:
            break
    assert reason == "stop_hit"

    # At 2R (peak of 110, gain=10 < 3R's 18) the same path must NOT yet
    # have floored at breakeven under the 3R variant - confirm it takes
    # the full 118 peak, not merely 2R's worth of gain, by checking the
    # 2R variant on the SAME path floors earlier (already at the 110 bar,
    # since gain=10 >= 2*6=12 is actually false too - use a path where 2R
    # clears at 110: R=6 => 2R=12, gain at 110 is 10, still short; so
    # neither variant floors until 118). This just documents that 3R
    # requires a materially larger move than 2R using the shared fixture
    # family above (test_stop_floors_at_breakeven_once_2r_reached_and_never_reverts).
    assert entry_price + main.MINERVINI_BREAKEVEN_R_3 * (entry_price - initial_stop) == 118.0


def test_3r_requires_a_bigger_move_than_2r_on_the_same_path():
    # Same risk (R=6, initial_stop=94) run to a peak of 113 (gain=13):
    # clears 2R (12) but not 3R (18). The 2R variant must have already
    # floored at breakeven while the 3R variant must still be sitting on
    # the flat initial_stop.
    close = np.array([100.0, 108.0, 113.0, 95.0])
    dates = pd.date_range("2026-01-01", periods=len(close)).astype(str).to_numpy()
    entry_day = dates[0]
    entry_price = 100.0
    initial_stop = 94.0
    atr_at_entry = 1.0

    running_max_2r = entry_price
    reason_2r = None
    running_max_3r = entry_price
    reason_3r = None
    for i in range(1, len(close)):
        sub = _sub_df(close, dates, i)
        reason_2r, running_max_2r = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max_2r,
            entry_price, main.MINERVINI_BREAKEVEN_R_2,
        )
        reason_3r, running_max_3r = main.minervini_vcp_exit_reason_breakeven(
            sub, entry_day, initial_stop, atr_at_entry, running_max_3r,
            entry_price, main.MINERVINI_BREAKEVEN_R_3,
        )
        if reason_2r or reason_3r:
            break
    # close=95 is above initial_stop (94) but below breakeven (100): the
    # 2R variant (already floored at breakeven) must exit here, while the
    # 3R variant (never reached 18-point gain, still flat at 94) must not.
    assert reason_2r == "stop_hit"
    assert reason_3r is None
