"""Tests for the live-LTP basis of the trailing stop (2026-09-17, explicit
user instruction "Replace with LTP - Must have" - live Fortis finding:
price was already >0.5R above entry but the trail hadn't activated,
because _trailing_stop_target only ever compared against the last CLOSED
candle. See that function's own docstring for the full reasoning,
including why round-robin scan cadence is explicitly UNCHANGED (accepted
by the user) - only the price basis moves from candle-close to live LTP."""
import datetime as dt

import pandas as pd

import main


def _today_df(closes, start_hour=9, start_minute=15, freq_min=5):
    mins = [start_hour * 60 + start_minute + i * freq_min for i in range(len(closes))]
    return pd.DataFrame({"Close": closes, "mins": mins})


_ENTRY_TS = dt.datetime(2026, 9, 9, 3, 45, tzinfo=dt.timezone.utc).timestamp()  # 09:15 IST
_TZ_OFF = 330  # IST


def test_live_price_activates_the_trail_even_when_last_close_has_not():
    # entry 100, initial stop 98 -> R = 2, activates at 101. Last CLOSED
    # candle is still 100.5 (below activation) but the live tick is 101.5 -
    # this is exactly the live Fortis scenario: real price ahead of the
    # last closed candle.
    today_df = _today_df([100.0, 100.5])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=101.5, known_peak=None,
    )
    assert peak == 101.5
    assert cand == 101.5 - main.TRAIL_ACTIVATE_R * 2.0


def test_live_price_below_activation_uses_it_over_a_higher_stale_close():
    # last CLOSED candle already cleared activation (103), but the live
    # tick has since pulled back below the 0.5R activation line (100.5) -
    # the live price must govern, not the stale close, since "must have
    # LTP" means LTP is now the source of truth whenever it's available.
    today_df = _today_df([100.0, 103.0])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=100.5, known_peak=None,
    )
    assert cand is None
    assert peak == 100.5  # still tracked as this tick's peak-so-far


def test_known_peak_carries_forward_and_only_ratchets_up():
    # position already had a peak of 110 recorded from an earlier tick;
    # this tick's live price (108) is below that peak but still above
    # activation - the persisted peak must win, never regress to the
    # current tick's lower live price.
    today_df = _today_df([100.0])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=108.0, known_peak=110.0,
    )
    assert peak == 110.0
    assert cand == 110.0 - main.TRAIL_ACTIVATE_R * 2.0


def test_live_price_new_high_ratchets_known_peak_up():
    today_df = _today_df([100.0])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=112.0, known_peak=110.0,
    )
    assert peak == 112.0
    assert cand == 112.0 - main.TRAIL_ACTIVATE_R * 2.0


def test_no_live_price_falls_back_to_candle_close_basis_unchanged():
    # live_price=None (e.g. a transient feed gap) must reproduce the
    # pre-existing candle-close behavior exactly.
    today_df = _today_df([100.0, 103.0, 106.0, 104.5])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=None, known_peak=999.0,
    )
    assert peak == 106.0  # candle-derived peak, NOT the irrelevant known_peak
    assert cand == 105.0


def test_zero_or_negative_live_price_is_treated_as_unavailable():
    # a live tick of 0/negative is never a real price (see
    # _maybe_place_real_entry's own identical ltp <= 0 guard) - must fall
    # back to the candle-close basis, not propose a nonsensical stop.
    today_df = _today_df([100.0, 103.0])
    peak, cand = main._trailing_stop_target(
        today_df, 100.0, 98.0, _ENTRY_TS, _TZ_OFF, live_price=0.0, known_peak=None,
    )
    assert peak == 103.0
    assert cand == 102.0
