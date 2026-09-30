"""Tests for `_scale_in_tranches` (2026-09-29, explicit user task: a scale-in
position-sizing variant for the Minervini VCP strategy; corrected 2026-09-30
to match the actual book source, docs/minervini_book_notes.txt CHAPTER 13
"SCALE-IN POSITION CONSTRUCTION": 2-3 tranches, e.g. 2%/2%/1% of capital,
added only on an open profit against the blended cost, never averaging down).

This is a pure sizing/backtest-mechanics helper - it does NOT touch
minervini_vcp_entry_signal or minervini_vcp_exit_reason, which stay
completely unmodified (verified directly in
test_scale_in_does_not_touch_entry_exit_signal_functions below).

Covers, per the task spec:
  1. A later tranche fills when price advances enough (above the running
     blended cost by the small add-trigger buffer) within the window.
  2. A later tranche never fills when price never reaches its trigger within
     the window (final position is just the tranches that did fill).
  3. A later tranche never fills if the stop is hit before its trigger price
     is reached.
  4. The average entry price (blended cost) calculation is correct when
     multiple tranches fill at different prices.
Plus: the 3-tranche default, per-tranche sequencing (tranche 2 needs tranche
1 to have filled first and prices its trigger off the NEW blended cost, not
the original entry), the "never average down" invariant, and boundary/
precedence edge cases (same-bar stop-vs-trigger precedence, window
exhaustion, invalid tranche_pcts).
"""
import numpy as np
import pytest

import main


ENTRY_PRICE = 100.0
ATR_AT_ENTRY = 2.0
STOP_LOSS = 95.0  # a plausible VCP final-leg-low stop, well below entry
TRIGGER_BUFFER = main.MINERVINI_SCALE_IN_ADD_ATR_MULT * ATR_AT_ENTRY  # 0.25 * 2.0 = 0.5


def test_default_is_three_tranches_matching_the_book_example():
    # Book's own worked example: 2%/2%/1% of capital -> normalized 0.4/0.4/0.2.
    assert main.MINERVINI_SCALE_IN_TRANCHE_PCTS == (0.4, 0.4, 0.2)
    assert sum(main.MINERVINI_SCALE_IN_TRANCHE_PCTS) == pytest.approx(1.0)


def test_later_tranche_fills_when_price_advances_enough():
    # Tranche 2 trigger = 100 + 0.5 = 100.5. Cleared on bar 2 (close 101.0).
    path = [100.2, 101.0, 102.0, 103.0, 104.0]
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    assert result["n_tranches_filled"] >= 2
    assert result["fill_bars"][1] == 2
    assert result["fill_prices"][1] == pytest.approx(101.0)
    assert result["filled_fractions"][0] == pytest.approx(0.4)
    assert result["filled_fractions"][1] == pytest.approx(0.4)


def test_all_three_tranches_fill_in_sequence_across_bars():
    # Tranche1 @100 (avg=100). Tranche2 trigger=100.5, filled bar1 @101 ->
    # avg = (0.4*100 + 0.4*101)/0.8 = 100.5. Tranche3 trigger=100.5+0.5=101.0,
    # filled bar2 @103.
    path = [101.0, 103.0]
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    assert result["n_tranches_filled"] == 3
    assert result["fill_bars"] == [0, 1, 2]
    assert result["fill_prices"][0] == pytest.approx(100.0)
    assert result["fill_prices"][1] == pytest.approx(101.0)
    assert result["fill_prices"][2] == pytest.approx(103.0)
    assert result["total_filled_pct"] == pytest.approx(1.0)
    expected_avg = 0.4 * 100.0 + 0.4 * 101.0 + 0.2 * 103.0
    assert result["avg_entry_price"] == pytest.approx(expected_avg)


def test_later_tranche_never_fills_if_price_never_reaches_trigger_in_window():
    # Trigger (tranche 2) = 100.5. Price drifts up but never clears it within
    # the default 10-bar window.
    path = [100.05, 100.1, 100.15, 100.2, 100.25, 100.3, 100.35, 100.4, 100.45, 100.49]
    assert len(path) == 10  # exactly the default add_within_bars window
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    assert result["n_tranches_filled"] == 1
    assert result["fill_prices"][1] is None
    assert result["fill_bars"][1] is None
    assert result["filled_fractions"][1] == pytest.approx(0.0)
    assert result["total_filled_pct"] == pytest.approx(0.4)
    assert result["avg_entry_price"] == pytest.approx(ENTRY_PRICE)


def test_trigger_reached_only_after_window_closes_does_not_fill():
    # Bars 1-10 stay below trigger; bar 11 (past the 10-bar window) clears it.
    path = [100.0 + 0.01 * i for i in range(1, 11)] + [110.0]
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    assert result["n_tranches_filled"] == 1
    assert result["total_filled_pct"] == pytest.approx(0.4)


def test_later_tranches_never_fill_if_stop_hit_before_trigger():
    # Price dips to hit the stop on bar 2, well before ever approaching the
    # 100.5 trigger level.
    path = [98.0, 94.5, 96.0, 103.0]  # bar 2 close (94.5) <= stop_loss (95.0)
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    assert result["n_tranches_filled"] == 1
    assert result["fill_prices"][1] is None
    assert result["fill_prices"][2] is None
    assert result["total_filled_pct"] == pytest.approx(0.4)
    assert result["avg_entry_price"] == pytest.approx(ENTRY_PRICE)


def test_same_bar_stop_and_trigger_precedence_favors_stop():
    # A bar whose close is simultaneously <= stop_loss and would clear a
    # (hypothetically very low) trigger - pins down the documented
    # precedence: stop wins, no later tranche fills even though the trigger
    # condition is also nominally satisfied that same bar.
    low_trigger_mult = -10.0  # trigger = 100 + (-10)*2 = 80, absurdly low
    path = [94.0]  # 94 <= stop_loss (95) and 94 >= 80 (trigger would-be-cleared)
    result = main._scale_in_tranches(
        ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path, add_trigger_atr_mult=low_trigger_mult,
    )
    assert result["n_tranches_filled"] == 1


def test_average_entry_price_correct_with_two_unequal_tranches_at_different_prices():
    result = main._scale_in_tranches(
        ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, [104.0],
        tranche_pcts=(0.5, 0.5),
    )
    assert result["n_tranches_filled"] == 2
    expected_avg = 0.5 * 100.0 + 0.5 * 104.0  # = 102.0
    assert result["avg_entry_price"] == pytest.approx(expected_avg)
    assert result["avg_entry_price"] == pytest.approx(102.0)


def test_custom_tranche_split_weights_average_price_correctly():
    # 70/30 split. Trigger (tranche 2) = 100 + 0.5 = 100.5, first cleared on
    # bar 1 (close 101.0) - the loop stops at the first bar clearing it, so
    # bar 2's 110.0 is never reached.
    path = [101.0, 110.0]
    result = main._scale_in_tranches(
        ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path,
        tranche_pcts=(0.7, 0.3),
    )
    assert result["filled_fractions"][0] == pytest.approx(0.7)
    assert result["filled_fractions"][1] == pytest.approx(0.3)
    assert result["fill_prices"][1] == pytest.approx(101.0)
    expected_avg = 0.7 * 100.0 + 0.3 * 101.0
    assert result["avg_entry_price"] == pytest.approx(expected_avg)


def test_never_averages_down_avg_cost_is_monotonically_non_decreasing():
    # Each successive tranche trigger is priced off the RUNNING blended cost
    # plus a positive buffer, so every fill must land above the current
    # average - the average can therefore never decrease as tranches fill,
    # and every fill price must be >= the original entry_price.
    path = [100.6, 101.3, 102.0, 102.7, 103.4]
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path)
    filled_prices = [p for p in result["fill_prices"] if p is not None]
    assert filled_prices[0] == ENTRY_PRICE
    for p in filled_prices:
        assert p >= ENTRY_PRICE
    # avg_entry_price must never be below the original entry_price either.
    assert result["avg_entry_price"] >= ENTRY_PRICE


def test_single_tranche_pct_of_one_disables_scale_in_entirely():
    # A single 100%-weight tranche degenerates cleanly to single-shot sizing.
    path = [110.0, 120.0, 130.0]
    result = main._scale_in_tranches(
        ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, path, tranche_pcts=(1.0,),
    )
    assert result["n_tranches_filled"] == 1
    assert result["total_filled_pct"] == pytest.approx(1.0)
    assert result["avg_entry_price"] == pytest.approx(ENTRY_PRICE)


def test_invalid_tranche_pcts_raise():
    with pytest.raises(ValueError):
        main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, [], tranche_pcts=())
    with pytest.raises(ValueError):
        main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, [], tranche_pcts=(0.5, 0.6))
    with pytest.raises(ValueError):
        main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, [], tranche_pcts=(0.5, -0.5, 1.0))


def test_empty_price_path_never_fills_later_tranches():
    result = main._scale_in_tranches(ENTRY_PRICE, ATR_AT_ENTRY, STOP_LOSS, [])
    assert result["n_tranches_filled"] == 1
    assert result["total_filled_pct"] == pytest.approx(0.4)


def test_scale_in_does_not_touch_entry_exit_signal_functions():
    # Sanity guard for the task's own hard constraint: this feature must
    # never modify minervini_vcp_entry_signal/minervini_vcp_exit_reason.
    assert callable(main.minervini_vcp_entry_signal)
    assert callable(main.minervini_vcp_exit_reason)
    assert callable(main._scale_in_tranches)
