"""Tests for the TREND-down 8-factor short mirror (2026-09-29, explicit
user instruction: "I need at least one strategy for the short sell...
this helps me downward trend of market... it's a must have" - built after
the RANGE VWAP-spike short mirror's three validation passes (target-
cluster fix, staged ladder, stricter entry filter) all left PFnet pinned
at 0.17-0.26. TREND is the one long-side engine in this codebase with
genuinely positive validated evidence, so this mirrors IT downward rather
than inventing a new signal - exactly the "TREND-down (8-factor score)
mirror" CLAUDE.md already flagged as scoped out of the original short-
selling pass. These tests mirror test_universal_score_engine.py's own
building-block and score tests, plus one end-to-end DB round trip through
_short_signal_core in the "trend" regime."""
import os
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd
import pytest

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- bearish building blocks -------------------------------------------------

def _flat_high_low_close_df_desc(n=40, start=130.0, end=100.0):
    return pd.DataFrame({
        "High": np.linspace(start, end, n) + 0.5,
        "Low": np.linspace(start, end, n) - 0.5,
        "Close": np.linspace(start, end, n),
    })


def test_swing_structure_bearish_true_for_a_clean_downtrend():
    df = _flat_high_low_close_df_desc(n=40)
    assert main._swing_structure_bearish(df) is True


def test_swing_structure_bearish_none_when_not_enough_history():
    df = _flat_high_low_close_df_desc(n=10)
    assert main._swing_structure_bearish(df) is None


def test_swing_structure_bearish_false_for_an_uptrend():
    df = pd.DataFrame({
        "High": np.linspace(100, 130, 40) + 0.5,
        "Low": np.linspace(100, 130, 40) - 0.5,
        "Close": np.linspace(100, 130, 40),
    })
    assert main._swing_structure_bearish(df) is False


def test_relative_strength_bearish_true_when_symbol_underperforms_index():
    sym = np.linspace(100, 90, 25)    # -10%
    idx = np.linspace(100, 105, 25)   # +5%
    assert main._relative_strength_bearish(sym, idx) is True


def test_relative_strength_bearish_false_when_symbol_outperforms_index():
    sym = np.linspace(100, 130, 25)   # +30%
    idx = np.linspace(100, 90, 25)    # -10%
    assert main._relative_strength_bearish(sym, idx) is False


def test_index_trend_bearish_true_for_a_falling_index():
    idx = np.linspace(130, 100, 30)
    assert main._index_trend_bearish(idx, 9, 21, "ema") is True


def test_index_trend_bearish_false_for_a_rising_index():
    idx = np.linspace(100, 130, 30)
    assert main._index_trend_bearish(idx, 9, 21, "ema") is False


# ---- _compute_universal_entry_score_short ------------------------------------

def _bearish_fixture(n=60):
    df = pd.DataFrame({
        "High": np.linspace(130, 100, n) + 0.5,
        "Low": np.linspace(130, 100, n) - 0.5,
        "Close": np.linspace(130, 100, n),
        "Volume": np.concatenate([np.full(n - 1, 1000.0), [3000.0]]),
    })
    today_df = df.iloc[-5:].copy()
    closes = df["Close"].to_numpy()
    sma_f = main._moving_average(closes, 9, "ema")
    sma_s = main._moving_average(closes, 21, "ema")
    return df, today_df, sma_f, sma_s


def test_universal_entry_score_short_high_for_a_clean_downtrend_with_index():
    df, today_df, sma_f, sma_s = _bearish_fixture()
    index_closes = np.linspace(210, 200, 60)  # bearish index too
    out = main._compute_universal_entry_score_short(
        df, today_df, True, sma_f, sma_s, index_closes, 9, 21, "ema", vol_ratio=2.0,
    )
    assert out["max_score"] == 100
    assert out["score_pct"] >= main.UNIVERSAL_ENTRY_SCORE_MIN
    assert out["entry_allowed"] is True
    assert out["rejection_reasons"] == []


def test_universal_entry_score_short_renormalizes_when_no_index_reference():
    df, today_df, sma_f, sma_s = _bearish_fixture()
    out = main._compute_universal_entry_score_short(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0,
    )
    assert out["max_score"] == 80
    assert "relative_strength" not in out["breakdown"]
    assert "index_trend" not in out["breakdown"]


def test_universal_entry_score_short_rejects_on_thin_liquidity():
    df, today_df, sma_f, sma_s = _bearish_fixture()
    out = main._compute_universal_entry_score_short(df, today_df, False, sma_f, sma_s, None, 9, 21, "ema")
    assert "liquidity_inadequate" in out["rejection_reasons"]
    assert out["entry_allowed"] is False


def test_universal_entry_score_short_never_raises_on_a_too_short_history():
    df = pd.DataFrame({"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [500.0]})
    out = main._compute_universal_entry_score_short(df, df, False, None, None, None, 9, 21, "ema")
    assert out["entry_allowed"] is False
    assert out["score"] == 0
    assert out["breakdown"]["ema_cross"] is None
    assert out["breakdown"]["rsi_band"] is None
    assert out["breakdown"]["structure_hh_hl"] is None


def test_universal_entry_score_short_and_long_disagree_on_the_same_bullish_data():
    # A clean UPTREND must NOT score as a bearish setup - mutual exclusivity
    # mirror of test_short_entry_and_long_entry_are_mutually_exclusive in
    # test_short_selling.py, at the TREND-score level instead of the RANGE
    # VWAP-trigger level.
    df = pd.DataFrame({
        "High": np.linspace(100, 130, 60) + 0.5,
        "Low": np.linspace(100, 130, 60) - 0.5,
        "Close": np.linspace(100, 130, 60),
        "Volume": np.concatenate([np.full(59, 1000.0), [3000.0]]),
    })
    today_df = df.iloc[-5:].copy()
    closes = df["Close"].to_numpy()
    sma_f = main._moving_average(closes, 9, "ema")
    sma_s = main._moving_average(closes, 21, "ema")
    out = main._compute_universal_entry_score_short(df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0)
    assert out["entry_allowed"] is False


# ---- end-to-end _short_signal_core in the "trend" regime ---------------------

class _FakeYFinance:
    def __init__(self, df):
        self._df = df

    def __call__(self, symbol, period, interval):
        # Anchored to TODAY's IST calendar date at market open (03:45 UTC
        # = 09:15 IST), not a fixed date (2026-09-29 fix, day-rollover
        # flake: a hardcoded calendar date here broke the moment IST
        # crossed midnight mid-session, since _short_signal_core's
        # today_df filter drops every bar whose date_local isn't today -
        # and simply anchoring to raw "now" instead left too few bars in
        # today's own session near IST midnight). Mirrors the same
        # UTC+offset arithmetic _short_signal_core itself uses.
        today_ist_midnight = (pd.Timestamp.utcnow() + pd.Timedelta(minutes=main.IST_OFFSET_MIN)).normalize()
        session_start_utc = (today_ist_midnight - pd.Timedelta(minutes=main.IST_OFFSET_MIN)
                              + pd.Timedelta(hours=3, minutes=45))
        return self._df.assign(Date=pd.date_range(session_start_utc, periods=len(self._df), freq="5min", tz="UTC"))


def _clean_downtrend_5m_df():
    # 70 5-min bars (all within one calendar day after the IST offset, so
    # today_df == df - no artificial day-boundary split): 60 bars of a
    # gentle down-drifting oscillation (establishes bearish swing
    # structure/RSI/EMA-cross baseline) followed by a 10-bar breakdown leg
    # into a final volume-spike candle with a long lower wick (support
    # genuinely broken, ATR wide enough that the close isn't flagged as
    # "too extended from VWAP" - real breakdown candles widen ATR right
    # when price also moves furthest from session VWAP, unlike a
    # perfectly smooth all-day linspace decline, which was tried first and
    # numerically failed both the too_extended_from_vwap and
    # reward_risk_below_minimum rejection filters).
    i = np.arange(60)
    base1 = 101.5 + 0.5 * np.sin(i / 3.0) - np.linspace(0, 0.5, 60)
    base2 = np.linspace(base1[-1] - 0.15, 99.0, 10)
    close = np.concatenate([base1, base2])
    open_ = close + np.concatenate([np.full(60, 0.15), np.full(9, 0.15), [0.6]])
    high_off = np.concatenate([np.full(60, 0.2), np.full(9, 0.2), [0.3]])
    low_off = np.concatenate([np.full(60, 0.2), np.full(9, 0.2), [7.0]])
    high = np.maximum(open_, close) + high_off
    low = np.minimum(open_, close) - low_off
    volume = np.full(70, 1000.0)
    volume[-1] = 5000.0
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})


def test_short_signal_core_enters_a_trend_short_on_a_clean_downtrend(monkeypatch):
    _fresh_db()
    df = _clean_downtrend_5m_df()
    monkeypatch.setattr(main, "fetch_ohlc", _FakeYFinance(df))
    monkeypatch.setattr(main, "get_fx_to_inr", lambda currency: 1.0)
    monkeypatch.setattr(main.sentiment_signals, "allows_entry", lambda symbol, day: (True, "no_data"))
    monkeypatch.setattr(main, "_liquidity_gate", lambda df: (True, []))
    monkeypatch.setattr(main, "_likely_lower_circuit_locked", lambda df, today_str: False)
    monkeypatch.setattr(main, "_classify_market_regime", lambda *a, **k: "trend")

    result = main._short_signal_core(
        symbol="TESTTRENDSHORT.NS", capital=400000, daily_risk_pct=2.0, risk_per_trade_pct=2.0,
        stop_pct=2.0, rr=3.0, sma_fast=9, sma_slow=21, interval="5m",
        tz_offset_min=main.IST_OFFSET_MIN, open_min=0, close_min=1439, squareoff_min=1438,
        trade_weekends=True, currency="INR", max_hold_minutes=120.0, ma_type="ema",
        require_real_tradability=False,
    )
    assert result["action_taken"] == "entered_short", result
    assert result["market_regime"] == "trend"

    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM signal_state_short WHERE symbol = ?", ("TESTTRENDSHORT.NS",)).fetchone()
        assert row is not None
        assert row["strategy"] == main.TREND_SHORT_STRATEGY_TAG
        assert row["stop_loss"] > row["entry_price"]
        assert row["target"] < row["entry_price"]
        assert row["qty"] > 0


def test_short_signal_core_trend_regime_no_signal_on_a_clean_uptrend(monkeypatch):
    _fresh_db()
    n = 200
    close = np.linspace(100.0, 130.0, n)
    open_ = close - 0.3
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    volume = np.full(n, 1000.0)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})
    monkeypatch.setattr(main, "fetch_ohlc", _FakeYFinance(df))
    monkeypatch.setattr(main, "get_fx_to_inr", lambda currency: 1.0)
    monkeypatch.setattr(main, "_classify_market_regime", lambda *a, **k: "trend")

    result = main._short_signal_core(
        symbol="TESTUPTREND.NS", capital=400000, daily_risk_pct=2.0, risk_per_trade_pct=2.0,
        stop_pct=2.0, rr=3.0, sma_fast=9, sma_slow=21, interval="5m",
        tz_offset_min=main.IST_OFFSET_MIN, open_min=0, close_min=1439, squareoff_min=1438,
        trade_weekends=True, currency="INR", max_hold_minutes=120.0, ma_type="ema",
        require_real_tradability=False,
    )
    assert result["action_taken"] == "no_signal", result
