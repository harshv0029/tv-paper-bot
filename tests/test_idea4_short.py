"""Tests for Idea 4's short mirror ("ride losers down, no target",
2026-09-29, explicit user instruction "Prep short mirror for others too"
per CLAUDE.md's 2026-09-28 standing thumb rule). idea4_entry_signal_short
wraps the REAL, unmodified _compute_universal_entry_score_short (already
covered by test_universal_score_engine.py/the TREND-down short mirror's
own tests) with the same daily-bar rolling-VWAP substitute and an explicit
EMA9<EMA21 pre-filter idea4_entry_signal itself uses, mirrored. Not wired
into main.py's live scan/scheduler/order path - see strategy_registry.py's
"registering != trading" principle."""
import numpy as np
import pandas as pd

import main


def _idea4_downtrend_fixture(n=80, start=1004.3, end=1000.0, breakdown_close=998.5):
    """A shallow, smooth downtrend (mirrors tests/test_idea4.py's own
    uptrend fixture) ending in a breakdown bar clearing the trailing
    20-bar support on a volume surge."""
    mild = np.linspace(start, end, n - 1)
    close = np.concatenate([mild, [breakdown_close]])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.concatenate([np.full(n - 1, 1000.0), [3000.0]])
    return pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "Open": open_, "High": close + 1.0, "Low": close - 1.0, "Close": close, "Volume": volume,
    })


# ---- idea4_entry_signal_short --------------------------------------------

def test_idea4_short_entry_fires_on_a_clean_downtrend_with_volume_surge():
    df = _idea4_downtrend_fixture()
    out = main.idea4_entry_signal_short(df)
    assert out is not None
    assert out["entry_price"] == df["Close"].iloc[-1]
    assert out["stop_loss"] > out["entry_price"]
    assert out["atr_at_entry"] > 0


def test_idea4_short_entry_none_on_insufficient_history():
    df = _idea4_downtrend_fixture(n=30)
    assert main.idea4_entry_signal_short(df) is None


def test_idea4_short_entry_none_when_ema_fast_not_below_ema_slow():
    close = np.linspace(1000.0, 1004.3, 80)  # uptrend: EMA9 > EMA21
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    df = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=80, freq="B").strftime("%Y-%m-%d"),
        "Open": open_, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": np.concatenate([np.full(79, 1000.0), [3000.0]]),
    })
    assert main.idea4_entry_signal_short(df) is None


def test_idea4_short_entry_none_when_universal_score_gate_rejects(monkeypatch):
    df = _idea4_downtrend_fixture()
    monkeypatch.setattr(main, "_compute_universal_entry_score_short",
                         lambda *a, **k: {"entry_allowed": False, "score_pct": 40.0})
    assert main.idea4_entry_signal_short(df) is None


def test_idea4_short_entry_stop_uses_atr_mult():
    df = _idea4_downtrend_fixture()
    out = main.idea4_entry_signal_short(df)
    atr_series = main._atr_series(df)
    expected_stop = out["entry_price"] + main.IDEA4_ATR_STOP_MULT * float(atr_series.iloc[-1])
    assert abs(out["stop_loss"] - expected_stop) < 1e-9


# ---- idea4_exit_reason_short -----------------------------------------------

def test_idea4_short_exit_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 99.0, 98.0],
    })
    assert main.idea4_exit_reason_short(df, "2026-01-02", stop_loss=110.0) is None


def test_idea4_short_exit_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05"],
        "Close": [100.0, 110.5],
    })
    assert main.idea4_exit_reason_short(df, "2026-01-02", stop_loss=110.0) == "stop_hit"


def test_idea4_short_exit_stop_hit_takes_priority_over_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=25).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 24 + [111.0]})
    assert main.idea4_exit_reason_short(df, dates[0], stop_loss=110.0) == "stop_hit"


def test_idea4_short_exit_max_hold_exit_after_20_days():
    dates = pd.bdate_range("2026-01-02", periods=22).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 22})
    assert main.idea4_exit_reason_short(df, dates[0], stop_loss=150.0) == "max_hold_exit"


def test_idea4_short_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=20).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * 20})
    assert main.idea4_exit_reason_short(df, dates[0], stop_loss=150.0) is None
