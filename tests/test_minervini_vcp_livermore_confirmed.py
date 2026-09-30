"""Tests for the Livermore two-pullback confirmation entry filter layered
on top of the Minervini VCP strategy (2026-09-30, explicit user
instruction, per docs/minervini_book_notes.txt's "THE LIVERMORE SYSTEM"
note ~line 395: don't buy the first breakout - wait for a pullback, a
rally, a second pullback, then buy only once price exceeds the SECOND
rally's high).

See main.py's own header comment directly above
minervini_vcp_entry_signal_livermore_confirmed for the full disclosed
algorithm (fractal swing-point width, backward breakout reconstruction,
failed-retest invalidation, stop-loss choice). These tests reuse the same
hand-engineered-fixture style as test_minervini_vcp.py: the shared base
fixture is copied here (not imported) to keep this file self-contained,
matching this repo's existing per-file fixture convention."""
import numpy as np
import pandas as pd
import pytest

import main


# ---- shared fixture: the same validated base VCP breakout as -----------
# ---- test_minervini_vcp.py's own fixture, PLUS a two-pullback tail -----

def _base_arrays():
    """Identical to test_minervini_vcp.py's _minervini_vcp_fixture: 220
    bars of uptrend (50->150) + an 80-bar tail tracing a genuine tightening
    VCP base, ending on bar 299 with a breakout close of 182.0 above a
    pivot_high of 175.3, stop (final_leg_low) of 165.95, and a volume
    surge on that one bar only. Returns the raw High/Low/Close/Volume
    arrays (300 bars) so callers can extend the tail further."""
    close1 = np.linspace(50.0, 150.0, 220)
    verts_x = [220, 240, 252, 264, 276, 298, 299]
    verts_y = [150.0, 180.0, 140.0, 175.0, 166.25, 170.0, 182.0]
    tail_idx = np.arange(220, 300)
    mid_tail = np.interp(tail_idx, verts_x, verts_y)
    mid = np.concatenate([close1, mid_tail])
    high = mid + 0.3
    low = mid - 0.3
    close = mid.copy()
    volume = np.full(300, 1000.0)
    volume[-1] = 5000.0
    return high, low, close, volume


# Post-breakout tail vertices (bar index, mid price), starting at bar 299
# (the breakout close, 182.0): a genuine reaction-low #1 (306), rally #1
# high (313), reaction-low #2 (320), then the second rally's high (327),
# a brief hold (334) that gives the fractal detector its
# LIVERMORE_VCP_FRACTAL_WIDTH=3 bars of confirmation on both sides of that
# peak, and a final push (341) that closes above the second rally's high -
# the bar the confirmed signal should fire on. Spacing of 7 bars between
# every vertex comfortably clears the width=3 fractal confirmation window
# on each side of every swing point.
_EXT_VERTS_X = [299, 306, 313, 320, 327, 334, 341]
_EXT_VERTS_Y_CLEAN = [182.0, 178.0, 195.0, 188.0, 205.0, 200.0, 210.0]


def _extend(ext_verts_y, base=None):
    high0, low0, close0, vol0 = base or _base_arrays()
    ext_idx = np.arange(299, 342)
    ext_mid = np.interp(ext_idx, _EXT_VERTS_X, ext_verts_y)
    mid = np.concatenate([close0[:299], ext_mid])
    high = mid + 0.3
    low = mid - 0.3
    close = mid.copy()
    volume = np.full(len(mid), 1000.0)
    volume[299] = 5000.0
    return pd.DataFrame({"High": high, "Low": low, "Close": close, "Volume": volume})


def _livermore_fixture():
    return _extend(_EXT_VERTS_Y_CLEAN)


# ---- minervini_vcp_entry_signal_livermore_confirmed --------------------

def test_fires_only_after_completing_two_pullback_and_rally_cycles():
    df = _livermore_fixture()
    sig = main.minervini_vcp_entry_signal_livermore_confirmed(df)
    assert sig is not None
    # Entry fires on the final bar (210.0), strictly above the second
    # rally's high (205.3 with the +0.3 High offset baked into the swing
    # value), with the stop set at reaction low #2 (187.7), not the
    # original base pivot's stop (165.95).
    assert sig["entry_price"] == pytest.approx(210.0)
    assert sig["stop_loss"] == pytest.approx(187.7)
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_does_not_fire_on_the_raw_pivot_breakout_bar_alone():
    """Contrast directly against minervini_vcp_entry_signal on the SAME
    fixture truncated to end exactly at the breakout bar: the base signal
    fires there (as test_minervini_vcp.py already validates), but the
    confirmed filter must still be None - there's no room yet for even one
    pullback-and-rally cycle, let alone two."""
    df = _livermore_fixture()
    df_at_breakout = df.iloc[:300].reset_index(drop=True)
    assert main.minervini_vcp_entry_signal(df_at_breakout) is not None
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df_at_breakout) is None


def test_none_while_the_two_pullback_cycle_is_still_incomplete():
    # Truncate right after reaction low #2 (bar 320) forms but well before
    # the second rally's high (bar 327) even exists yet.
    df = _livermore_fixture().iloc[:322].reset_index(drop=True)
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df) is None


def test_none_when_price_only_holds_above_pivot_without_a_higher_high():
    # A bar that merely closes above the original pivot (175.3) but not
    # above the second rally's high (205.3) must not fire - this is the
    # "genuine higher-high, not just holding above support" bar the task
    # is built around.
    df = _livermore_fixture().iloc[:328].reset_index(drop=True)
    assert df["Close"].iloc[-1] > 175.3  # comfortably above the base pivot
    assert df["Close"].iloc[-1] < 205.3  # but not above the 2nd rally high
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df) is None


def test_none_when_the_pullback_breaks_materially_below_the_original_pivot():
    """A failed retest invalidates the setup rather than merely delaying
    it: reaction low #1 dips to 160.0, below the base pivot's own stop
    (final_leg_low = 165.95), so even though the rest of the tail still
    traces out a complete two-rally structure with a higher high, the
    filter must return None."""
    ext_verts_y_failed = [182.0, 160.0, 195.0, 188.0, 205.0, 200.0, 210.0]
    df = _extend(ext_verts_y_failed)
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df) is None


def test_none_without_a_qualifying_breakout_in_the_lookback_window():
    # No volume surge anywhere -> minervini_vcp_entry_signal never fires
    # for any historical day -> _find_livermore_breakout finds nothing.
    df = _livermore_fixture()
    df.loc[299, "Volume"] = 1000.0
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df) is None


def test_none_when_trend_template_fails_today():
    df = _livermore_fixture()
    df.loc[df.index[-1], "Close"] = 10.0
    assert main.minervini_vcp_entry_signal_livermore_confirmed(df) is None


# ---- _find_livermore_breakout / _find_fractal_swings --------------------

def test_find_livermore_breakout_anchors_to_the_breakout_bar():
    df = _livermore_fixture()
    breakout_idx, invalidate_level = main._find_livermore_breakout(df)
    assert breakout_idx == 299
    assert invalidate_level == pytest.approx(165.95)


def test_find_fractal_swings_detects_the_alternating_low_high_sequence():
    df = _livermore_fixture()
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    swings = main._find_fractal_swings(highs, lows, 300, len(df) - 1, main.LIVERMORE_VCP_FRACTAL_WIDTH)
    kinds_in_order = [k for _, k, _ in swings]
    assert kinds_in_order == ["low", "high", "low", "high", "low"]
    idxs_in_order = [i for i, _, _ in swings]
    assert idxs_in_order == sorted(idxs_in_order)
