"""Unit tests for the physical-settlement force-close safety rule
(nse_fo_chain.py, 2026-09-16). Explicit user instruction after the
physical-settlement risk finding (single-stock F&O settles by physical
delivery of shares, confirmed live via RELIANCE's real scrip data -
both its FUTSTK future row and its option rows carry
pSettlementType="Physical", unlike every cash-settled index/commodity
underlying this module also resolves): "do it".

Run: pytest tests/ -v
"""
import datetime as dt

import nse_fo_chain


def d(y, m, day):
    return dt.date(y, m, day)


def test_is_physically_settled_true_for_a_confirmed_stock():
    assert nse_fo_chain.is_physically_settled("RELIANCE") is True


def test_is_physically_settled_false_for_every_cash_settled_underlying():
    for name in ("NIFTY", "BANKNIFTY", "SENSEX", "GOLD", "GOLDM", "SILVER", "SILVERM",
                 "CRUDEOIL", "CRUDEOILM"):
        assert nse_fo_chain.is_physically_settled(name) is False


def test_is_physically_settled_false_for_an_unknown_underlying():
    assert nse_fo_chain.is_physically_settled("NOT_A_REAL_SYMBOL") is False


def test_must_force_close_is_always_false_for_a_cash_settled_underlying():
    # Even on the expiry date itself - the rule is a no-op for anything
    # not in STOCK_FO_UNDERLYINGS.
    assert nse_fo_chain.must_force_close_before_expiry(
        "NIFTY", "2026-10-27", as_of=d(2026, 10, 27),
    ) is False


def test_must_force_close_is_false_well_before_expiry():
    assert nse_fo_chain.must_force_close_before_expiry(
        "RELIANCE", "2026-10-27", as_of=d(2026, 10, 10),
    ) is False


def test_must_force_close_is_true_exactly_at_the_configured_buffer():
    buffer_days = nse_fo_chain.PHYSICAL_SETTLEMENT_FORCE_CLOSE_DAYS_BEFORE_EXPIRY
    as_of = d(2026, 10, 27) - dt.timedelta(days=buffer_days)
    assert nse_fo_chain.must_force_close_before_expiry("RELIANCE", "2026-10-27", as_of=as_of) is True


def test_must_force_close_is_false_one_day_before_the_buffer_kicks_in():
    buffer_days = nse_fo_chain.PHYSICAL_SETTLEMENT_FORCE_CLOSE_DAYS_BEFORE_EXPIRY
    as_of = d(2026, 10, 27) - dt.timedelta(days=buffer_days + 1)
    assert nse_fo_chain.must_force_close_before_expiry("RELIANCE", "2026-10-27", as_of=as_of) is False


def test_must_force_close_is_true_on_expiry_day_itself():
    assert nse_fo_chain.must_force_close_before_expiry(
        "RELIANCE", "2026-10-27", as_of=d(2026, 10, 27),
    ) is True


def test_must_force_close_is_true_past_expiry_too():
    # A position that somehow survived past its own expiry date must
    # still be flagged, not silently treated as "no longer applicable".
    assert nse_fo_chain.must_force_close_before_expiry(
        "RELIANCE", "2026-10-27", as_of=d(2026, 11, 1),
    ) is True


def test_must_force_close_defaults_as_of_to_today_when_not_given():
    # Just confirm it doesn't raise and returns a bool when as_of is
    # omitted - real "today" varies by test run, so no fixed assertion
    # on the result itself.
    result = nse_fo_chain.must_force_close_before_expiry("RELIANCE", "2099-01-01")
    assert isinstance(result, bool)


def test_must_force_close_works_for_a_future_not_just_an_option():
    # The rule takes underlying+expiry only - no option-vs-future
    # distinction in its signature, matching the confirmed finding that
    # RELIANCE's FUTURE (not just its options) is also physically
    # settled.
    buffer_days = nse_fo_chain.PHYSICAL_SETTLEMENT_FORCE_CLOSE_DAYS_BEFORE_EXPIRY
    as_of = d(2026, 10, 27) - dt.timedelta(days=buffer_days)
    assert nse_fo_chain.must_force_close_before_expiry("RELIANCE", "2026-10-27", as_of=as_of) is True
