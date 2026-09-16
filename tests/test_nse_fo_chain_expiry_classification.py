"""Unit tests for nse_fo_chain.classify_expiries_weekly_monthly, added
2026-09-16 for F&O chain monitoring (weekly/monthly tracked separately).
Pure date-math, no network/Kotak dependency - every other nse_fo_chain
function requires a live Kotak session and isn't unit-testable here.

Run: pytest tests/ -v
"""
import datetime as dt

import nse_fo_chain


def d(y, m, day):
    return dt.date(y, m, day)


def test_picks_soonest_as_weekly_and_last_this_month_as_monthly():
    expiries = [d(2026, 9, 18), d(2026, 9, 25), d(2026, 10, 2), d(2026, 10, 30)]
    result = nse_fo_chain.classify_expiries_weekly_monthly(expiries)
    assert result["weekly"] == d(2026, 9, 18)
    assert result["monthly"] == d(2026, 9, 25)  # latest expiry still in September


def test_monthly_is_last_expiry_in_the_soonest_expirys_own_month():
    # e.g. run on the last day of September, only October expiries remain -
    # "this month" is now October (the soonest expiry's month), so October's
    # OWN latest listed expiry is correctly October's monthly contract.
    expiries = [d(2026, 10, 1), d(2026, 10, 8), d(2026, 10, 29)]
    result = nse_fo_chain.classify_expiries_weekly_monthly(expiries)
    assert result["weekly"] == d(2026, 10, 1)
    assert result["monthly"] == d(2026, 10, 29)


def test_weekly_and_monthly_can_legitimately_be_equal_in_final_week_of_month():
    expiries = [d(2026, 9, 30)]  # the month's only remaining (and last) expiry
    result = nse_fo_chain.classify_expiries_weekly_monthly(expiries)
    assert result["weekly"] == d(2026, 9, 30)
    assert result["monthly"] == d(2026, 9, 30)


def test_empty_input_returns_both_none():
    assert nse_fo_chain.classify_expiries_weekly_monthly([]) == {"weekly": None, "monthly": None}


def test_single_expiry_is_both_weekly_and_monthly():
    expiries = [d(2026, 11, 5)]
    result = nse_fo_chain.classify_expiries_weekly_monthly(expiries)
    assert result["weekly"] == d(2026, 11, 5)
    assert result["monthly"] == d(2026, 11, 5)
