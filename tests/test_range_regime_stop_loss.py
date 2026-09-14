"""Tests for the RANGE regime stop-loss fix (2026-09-14). Root cause:
_auto_signal_core's stop-loss for every regime was
`max(structural_low, stop_loss_cap)` - the most recent
UNIVERSAL_STRUCTURE_LOOKBACK-bar low, capped at stop_pct% max risk,
whichever is tighter. That's correct for a TREND breakout (walking away
from its own recent low) but degenerate for RANGE mean-reversion, which
enters AT a fresh local low by construction - structural_low collapses to
~last_close there, so stop_dist collapses to ~0. Confirmed (52-symbol/
60-day validation replay, run 34858413071's era) as the root cause of
RANGE's 0.5% win rate: a near-zero stop gets hit by ordinary bar noise
almost immediately, AND inflates the risk-based qty past the notional/
tranche cap so RANGE trades sized at the full tranche almost every time.
Fix: _range_regime_stop_loss uses an ATR-multiple floor instead, still
capped at stop_loss_cap exactly as before."""
import numpy as np
import pandas as pd

import main


def _flat_df_with_a_sharp_final_dip(bars: int = 30, base: float = 100.0) -> pd.DataFrame:
    """A quiet, essentially flat series (small noise, real ATR>0) whose
    LAST bar plunges hard and closes near its own low - exactly the shape
    of a RANGE mean-reversion entry bar (close well below the lower VWAP
    band). The final bar's low is also the series' own minimum, so the
    OLD structural_low logic would peg the stop right at (or just below)
    last_close - the degenerate near-zero distance this fix targets."""
    rows = []
    for i in range(bars - 1):
        c = base + 0.1 * np.sin(i / 3.0)
        rows.append({"Open": c, "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 1000})
    # Sharp down bar: opens near the last quiet close, closes near its own low.
    plunge_close = base - 3.0
    rows.append({"Open": base, "High": base + 0.1, "Low": plunge_close - 0.05, "Close": plunge_close, "Volume": 5000})
    return pd.DataFrame(rows)


def test_range_regime_stop_loss_is_not_degenerate_on_a_fresh_local_low():
    df = _flat_df_with_a_sharp_final_dip()
    last_close = float(df["Close"].iloc[-1])
    structural_low = float(df["Low"].iloc[-21:].min())  # UNIVERSAL_STRUCTURE_LOOKBACK=20 (+current bar)

    # The scenario this bug requires: the OLD logic's stop distance really
    # would have been near-zero (structural_low sits right at/just under
    # last_close, since the entry bar itself made the series' new low).
    old_stop_dist = last_close - structural_low
    assert old_stop_dist < 0.5, f"fixture must reproduce the degenerate-stop scenario, got dist={old_stop_dist}"

    stop_loss_cap = last_close * (1 - 2.0 / 100)  # stop_pct=2.0 default
    new_stop = main._range_regime_stop_loss(last_close, df, stop_loss_cap)
    new_stop_dist = last_close - new_stop

    assert new_stop_dist > old_stop_dist, "fix must widen the degenerate stop, not match the old near-zero distance"
    # ATR-anchored, not just falling back to the 2% cap by accident -
    # confirms the ATR branch actually ran rather than always hitting the cap.
    atr_val = main._compute_atr_value(df)
    assert atr_val and atr_val > 0
    expected_atr_stop = last_close - main.RANGE_STOP_ATR_MULT * atr_val
    assert new_stop == max(expected_atr_stop, stop_loss_cap)


def test_range_regime_stop_loss_never_exceeds_the_stop_pct_cap():
    df = _flat_df_with_a_sharp_final_dip()
    last_close = float(df["Close"].iloc[-1])
    # A deliberately tight cap (0.1% max risk) - the ATR floor should be
    # miles wider than this, so the cap must still win ("tighter wins"
    # invariant preserved, only the RANGE-specific input distance changed).
    tight_cap = last_close * (1 - 0.1 / 100)
    stop = main._range_regime_stop_loss(last_close, df, tight_cap)
    assert stop == tight_cap


def test_range_regime_stop_loss_falls_back_to_cap_when_atr_unavailable():
    # Too few bars for ATR(14) to compute at all.
    df = pd.DataFrame([
        {"Open": 100, "High": 100.3, "Low": 99.7, "Close": 100, "Volume": 1000},
        {"Open": 100, "High": 100.2, "Low": 98.5, "Close": 98.6, "Volume": 2000},
    ])
    last_close = 98.6
    stop_loss_cap = last_close * (1 - 2.0 / 100)
    stop = main._range_regime_stop_loss(last_close, df, stop_loss_cap)
    assert stop == stop_loss_cap
