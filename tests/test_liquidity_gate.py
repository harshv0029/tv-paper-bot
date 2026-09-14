"""Tests for the absolute liquidity/price-action gate (2026-09-14,
explicit user instruction backed by three live screenshot examples -
LEXUS-EQ, KKCL-EQ, RADIOCITY - of real trades taken into stocks with
long gaps of zero volume and a flatlined LTP) and the TREND-only
entry-candle-bullish check."""
import numpy as np
import pandas as pd

import main


def _bars(closes, volumes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    return pd.DataFrame({
        "Open": opens, "High": [c + 0.2 for c in closes], "Low": [c - 0.2 for c in closes],
        "Close": closes, "Volume": volumes,
    })


# ---- _liquidity_gate --------------------------------------------------------

def test_fails_closed_on_insufficient_history():
    df = _bars([10.0, 10.1], [1000, 1000])  # fewer than LIQUIDITY_GATE_LOOKBACK_BARS
    ok, reasons = main._liquidity_gate(df)
    assert ok is False
    assert "insufficient_history_for_liquidity_gate" in reasons


def test_rejects_a_zero_volume_bar_in_the_recent_window():
    # Mirrors the RADIOCITY screenshot: long stretches of visible price
    # with zero volume between real prints.
    df = _bars([10.0, 10.0, 10.0], [50_000, 0, 50_000])
    ok, reasons = main._liquidity_gate(df)
    assert ok is False
    assert "zero_volume_bar_in_recent_window" in reasons


def test_rejects_turnover_below_the_absolute_floor():
    # Real volume every bar, but turnover far below the Rs 5L floor -
    # relative gates (volume_ok/RVOL) could still pass this if the
    # symbol is ALWAYS this thin, which is exactly the gap this closes.
    df = _bars([6.14, 6.14, 6.14], [100, 100, 100])  # ~Rs 1,842 total turnover
    ok, reasons = main._liquidity_gate(df)
    assert ok is False
    assert "turnover_below_minimum" in reasons


def test_rejects_a_flatlined_price_even_with_real_volume():
    # Mirrors the KKCL-EQ screenshot: volume prints every bar but price
    # barely/never moves - no real two-sided trading.
    df = _bars([497.35, 497.35, 497.35], [50_000, 50_000, 50_000])
    ok, reasons = main._liquidity_gate(df)
    assert ok is False
    assert "price_not_moving" in reasons


def test_passes_on_a_genuinely_liquid_moving_tape():
    df = _bars([100.0, 100.5, 101.2], [50_000, 55_000, 60_000])
    ok, reasons = main._liquidity_gate(df)
    assert ok is True
    assert reasons == []


# ---- entry_candle_bullish (TREND path only) --------------------------------

def _closes_history(n=60, base=100.0, step=0.5):
    return np.linspace(base, base + step * n, n)


def test_trend_path_rejects_a_bearish_entry_candle():
    closes = list(_closes_history())
    closes[-1] = closes[-2] + 1.0  # still an uptrend read, but...
    opens = [c for c in closes]
    opens[-1] = closes[-1] + 0.5  # ...this candle itself closed BELOW its open (red)
    df = _bars(closes, [50_000] * len(closes), opens=opens)
    today_df = df.iloc[-20:]
    sma_f = main._moving_average(np.array(closes), 9, "ema")
    sma_s = main._moving_average(np.array(closes), 21, "ema")
    result = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0,
    )
    assert "entry_candle_not_bullish" in result["rejection_reasons"]
    assert result["entry_allowed"] is False


def test_trend_path_allows_a_bullish_entry_candle_liquidity_permitting():
    closes = list(_closes_history())
    opens = [c - 0.3 for c in closes]  # every candle closed above its own open (green)
    df = _bars(closes, [50_000] * len(closes), opens=opens)
    today_df = df.iloc[-20:]
    sma_f = main._moving_average(np.array(closes), 9, "ema")
    sma_s = main._moving_average(np.array(closes), 21, "ema")
    result = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0,
    )
    assert "entry_candle_not_bullish" not in result["rejection_reasons"]
    assert "zero_volume_bar_in_recent_window" not in result["rejection_reasons"]
    assert "price_not_moving" not in result["rejection_reasons"]
