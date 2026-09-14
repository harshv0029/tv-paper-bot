"""Tests for the economic-viability entry gate (2026-09-14, real-money
profitability investigation - see main.py's ROUND_TRIP_COST_PCT comment for
the full derivation). Root cause: qty sizing (main.py's
`qty = min(risk_based_qty, usable_capital_inr/notional_per_unit_inr)`)
always binds to the FULL tranche whenever stop_dist_pct < risk_per_trade_pct
(the common case), so nearly every trade pays the SAME round-trip cost
(~0.8% of notional) regardless of how small the target's own edge is. Since
brokerage/STT/exchange/SEBI/stamp/GST/slippage are all a pure % of notional,
the fix is a qty-INDEPENDENT price-level check: skip any entry whose own
target can't clear round-trip cost, before it ever gets sized."""
import datetime as real_datetime
import os
import tempfile

import pandas as pd
import pytest
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---------------------------------------------------------------------------
# _target_move_pct - hand-verified arithmetic
# ---------------------------------------------------------------------------

def test_target_move_pct_hand_verified():
    # last_close=100, target=100.8 -> exactly at the 0.8% cost floor
    assert main._target_move_pct(100.8, 100.0) == pytest.approx(0.8, abs=1e-9)
    # last_close=100, target=103 -> 3% move (typical default rr=3.0, stop_pct=2.0 case)
    assert main._target_move_pct(103.0, 100.0) == pytest.approx(3.0, abs=1e-9)
    # last_close=0 -> defensive divide-by-zero guard, not a crash
    assert main._target_move_pct(5.0, 0.0) == 0.0


def test_round_trip_cost_pct_matches_the_documented_cost_model():
    # Hand-worked from the SAME cost-model components used by
    # docs/TRADING_CONSTRAINTS.md's live cost model / the validation-replay
    # workflow's DEFAULT_COST_MODEL (brokerage 0.20%/side, STT 0.1%/side,
    # exchange txn 0.00297%/side, SEBI 0.0001%/side, stamp duty 0.015%
    # buy-only, GST 18% on brokerage+exchange+SEBI, slippage 0.05%/side).
    brokerage, exch, sebi, slippage = 0.0020, 0.0000297, 0.000001, 0.0005
    gst = 0.18 * (brokerage + exch + sebi)
    buy_leg = brokerage + exch + sebi + 0.00015 + 0.001 + slippage + gst
    sell_leg = brokerage + exch + sebi + 0.001 + slippage + gst
    round_trip_pct = (buy_leg + sell_leg) * 100
    assert round_trip_pct == pytest.approx(0.7942, abs=0.001)
    # ROUND_TRIP_COST_PCT (0.8) must sit just above the hand-computed real
    # cost, not below it (below it would let a guaranteed-loser trade
    # through the gate) and not implausibly far above it (that would reject
    # trades with real, cost-clearing edge).
    assert main.ROUND_TRIP_COST_PCT >= round_trip_pct
    assert main.ROUND_TRIP_COST_PCT - round_trip_pct < 0.05


# ---------------------------------------------------------------------------
# End-to-end wiring - _auto_signal_core actually applies the gate before
# sizing. bullish_engulfing chosen over orb_breakout for the fixture (same
# reason test_strategy_logic.py gives for skipping orb_breakout fixtures -
# a hand-built ORB fixture is brittle; bullish_engulfing's own trigger
# condition is a simple, exactly-specifiable two-candle pattern).
# ---------------------------------------------------------------------------

class _FixedUtcNow(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 5, 45, 0)  # UTC -> 11:15 IST, mid-session

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _bullish_engulfing_fixture():
    """25 5-minute bars, all today (2026-09-09, 09:15 IST onward): 23 flat/
    noisy baseline bars (close ~100, volume ~1000) so structural_low sits
    close to 100 and the volume-confirm average is a known ~1000, then a
    clean bearish bar (index 23) immediately followed by a clean bullish-
    engulfing bar (index 24, close > open, engulfs the prior candle body,
    high volume) - main._vwap... N/A here, this is the bullish_engulfing
    strategy's own trigger, hand-verified against its exact condition in
    main.py (cur_bullish and prev_bearish and cur_open<=prev_close and
    cur_close>=prev_open)."""
    base = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
    rows = []
    for i in range(23):
        c = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        rows.append({
            "Date": base + pd.Timedelta(minutes=5 * i), "Open": c, "High": c + 0.1,
            "Low": c - 0.1, "Close": c, "Volume": 1000,
        })
    # bar 23: clean bearish candle
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 23), "Open": 101.0, "High": 101.1,
        "Low": 99.6, "Close": 99.7, "Volume": 1000,
    })
    # bar 24: clean bullish engulfing candle, high volume
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 24), "Open": 99.5, "High": 101.6,
        "Low": 99.4, "Close": 101.5, "Volume": 3000,
    })
    return pd.DataFrame(rows)


def _run(rr):
    _fresh_db()
    fixture = _bullish_engulfing_fixture()
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture):
        return main._auto_signal_core(
            "TESTSTOCK.NS", currency="INR", strategy="bullish_engulfing",
            trend_sma=0, rr=rr,
        )


def test_tiny_rr_target_that_cannot_clear_cost_is_skipped_before_sizing():
    result = _run(rr=0.05)
    assert result["action_taken"] == "cost_uneconomic_skipped", (
        f"a target move this small must be rejected before sizing, got: {result}"
    )
    assert result["target_move_pct"] <= main.ROUND_TRIP_COST_PCT


def test_normal_rr_target_that_clears_cost_is_not_skipped_by_the_gate():
    result = _run(rr=10.0)
    assert result.get("action_taken") != "cost_uneconomic_skipped", (
        f"a comfortably cost-clearing target must not be rejected by the gate, got: {result}"
    )
