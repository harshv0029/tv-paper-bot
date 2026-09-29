"""Tests for Idea 4 (2026-09-29, explicit user instruction "Okay keep it
as idea 4 / Named / And build it properly", after a critical review of
every trade taken to date surfaced score-signal-4h-1d-retest-research.yml's
TARGET-axis finding). idea4_entry_signal wraps the REAL, unmodified
_compute_universal_entry_score (already covered by
test_universal_score_engine.py's own fixtures) with a daily-bar rolling-
VWAP substitute and an explicit EMA9>EMA21 pre-filter - these tests cover
that wrapper's own logic plus the new fixed-stop/no-target exit function.
Not wired into main.py's live scan/scheduler/order path - see
strategy_registry.py's "registering != trading" principle and this
session's own consistent boundary for every strategy built this way."""
import numpy as np
import pandas as pd

import main


def _idea4_uptrend_fixture(n=80, mild_end=1004.3, breakout_close=1005.0):
    """n-1 bars of a mild, near-flat grind up (shallow enough that a
    VOLUME_CONFIRM_LOOKBACK-bar rolling VWAP window and ATR both stay
    unremarkable) ending in a genuine breakout bar: closes above every
    High in the trailing UNIVERSAL_STRUCTURE_LOOKBACK-bar window (clears
    breakout_resistance AND sidesteps reward_risk_below_minimum, which
    only applies while price is still below resistance) on a volume
    surge, without a true-range jump big enough to trip
    atr_abnormally_wide. At a price/volume level that clears
    LIQUIDITY_MIN_15MIN_TURNOVER_INR comfortably."""
    mild = np.linspace(1000.0, mild_end, n - 1)
    close = np.concatenate([mild, [breakout_close]])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.concatenate([np.full(n - 1, 1000.0), [3000.0]])
    return pd.DataFrame({
        "Open": open_, "High": close + 0.3, "Low": close - 0.3,
        "Close": close, "Volume": volume,
    })


# ---- idea4_entry_signal -------------------------------------------------

def test_idea4_entry_fires_on_a_clean_uptrend_with_volume_surge():
    df = _idea4_uptrend_fixture()
    out = main.idea4_entry_signal(df)
    assert out is not None
    assert out["entry_price"] == df["Close"].iloc[-1]
    assert out["stop_loss"] < out["entry_price"]
    assert out["atr_at_entry"] > 0
    assert out["score_pct"] >= main.UNIVERSAL_ENTRY_SCORE_MIN


def test_idea4_entry_none_on_insufficient_history():
    df = _idea4_uptrend_fixture(n=30)
    assert main.idea4_entry_signal(df) is None


def test_idea4_entry_none_when_ema_fast_not_above_ema_slow():
    close = np.linspace(1008.0, 1000.0, 80)  # downtrend: EMA9 < EMA21
    df = pd.DataFrame({
        "Open": close - 0.05, "High": close + 0.5, "Low": close - 0.5,
        "Close": close, "Volume": np.concatenate([np.full(79, 1000.0), [3000.0]]),
    })
    assert main.idea4_entry_signal(df) is None


def test_idea4_entry_none_when_universal_score_gate_rejects(monkeypatch):
    df = _idea4_uptrend_fixture()
    monkeypatch.setattr(main, "_compute_universal_entry_score",
                         lambda *a, **k: {"entry_allowed": False, "score_pct": 40.0})
    assert main.idea4_entry_signal(df) is None


def test_idea4_entry_stop_uses_atr_mult():
    df = _idea4_uptrend_fixture()
    out = main.idea4_entry_signal(df)
    atr_series = main._atr_series(df)
    expected_stop = out["entry_price"] - main.IDEA4_ATR_STOP_MULT * float(atr_series.iloc[-1])
    assert abs(out["stop_loss"] - expected_stop) < 1e-9


# ---- idea4_exit_reason ----------------------------------------------------

def test_idea4_exit_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 101.0, 102.0],
    })
    assert main.idea4_exit_reason(df, "2026-01-02", stop_loss=90.0) is None


def test_idea4_exit_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05"],
        "Close": [100.0, 89.5],
    })
    assert main.idea4_exit_reason(df, "2026-01-02", stop_loss=90.0) == "stop_hit"


def test_idea4_exit_stop_hit_takes_priority_over_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=25).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 24 + [89.0]})
    assert main.idea4_exit_reason(df, dates[0], stop_loss=90.0) == "stop_hit"


def test_idea4_exit_max_hold_exit_after_20_days():
    dates = pd.bdate_range("2026-01-02", periods=22).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 22})
    assert main.idea4_exit_reason(df, dates[0], stop_loss=50.0) == "max_hold_exit"


def test_idea4_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=20).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 20})
    assert main.idea4_exit_reason(df, dates[0], stop_loss=50.0) is None
