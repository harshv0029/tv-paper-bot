"""Tests for confidence-proportional position sizing and the RANGE-regime
confidence-decay exit (2026-09-21, explicit user instruction, task #6:
"confidence should be directly proportional to the qty you take for entry
into that trade... as soon as u feel that your confidence is getting low
... u should exit or plan to exit"), designed in discussion with the user:
  - TREND confidence = universal_score's own composite score_pct/100.
  - RANGE confidence = _range_regime_confidence (new: RANGE previously had
    no continuous confidence measure at all, only a boolean entry trigger).
  - Linear sizing, 25% floor at the entry-confidence bar, 100% at each
    regime's own "full confidence" reference point.
  - RANGE gets its own decay-exit (range_confidence_weakened), symmetric
    with the existing TREND-only trend_weakened exit."""
import datetime as real_datetime
import json
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

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


class _FixedUtcNow(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 5, 45, 0)  # UTC -> 11:15 IST, mid-session

    @classmethod
    def utcnow(cls):
        return cls._fixed


# ---- Pure math: _vwap_deviation_z / _range_regime_confidence -------------

def _vwap_fixture(dip_close: float) -> pd.DataFrame:
    # A quiet session (small, symmetric noise -> a real, nonzero std-dev)
    # whose LAST bar dips to dip_close - same shape as the RANGE stop-loss
    # fixture, just parametrized on how far the final close sits.
    rows = []
    base = 100.0
    for i in range(10):
        c = base + (0.2 if i % 2 == 0 else -0.2)
        rows.append({"High": c + 0.1, "Low": c - 0.1, "Close": c, "Volume": 1000})
    rows.append({"High": base + 0.1, "Low": dip_close - 0.1, "Close": dip_close, "Volume": 2000})
    return pd.DataFrame(rows)


def test_vwap_deviation_z_is_positive_below_vwap_and_scales_with_distance():
    shallow = main._vwap_deviation_z(_vwap_fixture(99.5))
    deep = main._vwap_deviation_z(_vwap_fixture(95.0))
    assert shallow > 0
    assert deep > shallow  # a bigger dip is a bigger z-score


def test_vwap_deviation_z_none_on_too_few_bars_or_zero_volume():
    assert main._vwap_deviation_z(pd.DataFrame([{"High": 1, "Low": 1, "Close": 1, "Volume": 100}])) is None
    zero_vol = _vwap_fixture(99.5)
    zero_vol["Volume"] = 0.0
    assert main._vwap_deviation_z(zero_vol) is None


def test_range_regime_confidence_matches_norm_cdf_of_the_same_z():
    df = _vwap_fixture(97.0)
    z = main._vwap_deviation_z(df)
    conf = main._range_regime_confidence(df)
    assert conf == main._norm_cdf(z)
    assert 0.0 <= conf <= 1.0


def test_range_regime_confidence_none_when_z_is_none():
    assert main._range_regime_confidence(pd.DataFrame([{"High": 1, "Low": 1, "Close": 1, "Volume": 0}])) is None


def test_vwap_mean_reversion_entry_still_matches_its_own_bb_std_threshold():
    # Refactor sanity check: _vwap_mean_reversion_entry must still fire
    # exactly when z >= bb_std, unchanged behavior after extracting
    # _vwap_deviation_z out of it.
    df = _vwap_fixture(97.0)
    z = main._vwap_deviation_z(df)
    assert main._vwap_mean_reversion_entry(df, bb_std=z - 0.01) is True
    assert main._vwap_mean_reversion_entry(df, bb_std=z + 0.01) is False


# ---- Pure math: _confidence_size_multiplier -------------------------------

def test_confidence_size_multiplier_at_entry_floor_is_the_size_floor():
    assert main._confidence_size_multiplier(0.70, 0.70, 1.0) == main.CONFIDENCE_SIZE_FLOOR


def test_confidence_size_multiplier_at_or_above_full_is_one():
    assert main._confidence_size_multiplier(1.0, 0.70, 1.0) == 1.0
    assert main._confidence_size_multiplier(1.5, 0.70, 1.0) == 1.0  # never exceeds 1.0


def test_confidence_size_multiplier_is_linear_at_the_midpoint():
    mid = main._confidence_size_multiplier(0.85, 0.70, 1.0)
    expected = main.CONFIDENCE_SIZE_FLOOR + (1.0 - main.CONFIDENCE_SIZE_FLOOR) * 0.5
    assert mid == pytest.approx(expected)


def test_confidence_size_multiplier_never_scales_below_the_floor():
    assert main._confidence_size_multiplier(0.0, 0.70, 1.0) == main.CONFIDENCE_SIZE_FLOOR


def test_confidence_size_multiplier_degenerate_full_at_falls_back_to_one():
    assert main._confidence_size_multiplier(0.80, 0.70, 0.70) == 1.0
    assert main._confidence_size_multiplier(0.80, 0.70, 0.50) == 1.0


# ---- Integration: sizing wired into _auto_signal_core ---------------------

def _bullish_engulfing_fixture():
    base = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
    rows = []
    for i in range(23):
        c = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        rows.append({
            "Date": base + pd.Timedelta(minutes=5 * i), "Open": c, "High": c + 0.1,
            "Low": c - 0.1, "Close": c, "Volume": 1000,
        })
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 23), "Open": 101.0, "High": 101.1,
        "Low": 99.6, "Close": 99.7, "Volume": 1000,
    })
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 24), "Open": 99.5, "High": 101.6,
        "Low": 99.4, "Close": 101.5, "Volume": 3000,
    })
    return pd.DataFrame(rows)


def test_bullish_engulfing_sizing_is_unaffected_no_confidence_measure_exists():
    _fresh_db()
    fixture = _bullish_engulfing_fixture()
    with patch("main.dt.datetime", _FixedUtcNow), patch("main.fetch_ohlc", return_value=fixture):
        result = main._auto_signal_core(
            "TESTSTOCK.NS", currency="INR", strategy="bullish_engulfing", trend_sma=0, rr=10.0,
        )
    assert result["action_taken"] == "entered_long"
    assert result["confidence_sizing"]["confidence"] is None
    assert result["confidence_sizing"]["size_multiplier"] == 1.0


def _run_universal_score(regime: str, confidence_value: float):
    _fresh_db()
    fixture = _bullish_engulfing_fixture()  # any real, numeric OHLCV series works - the
    # regime/score-gating internals below are mocked directly rather than
    # relying on this fixture to organically satisfy every scoring gate.
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("main._classify_market_regime", return_value=regime), \
         patch("main._liquidity_gate", return_value=(True, [])), \
         patch("sentiment_signals.allows_entry", return_value=(True, "no_data")), \
         patch("main._vwap_mean_reversion_entry", return_value=True), \
         patch("main._range_regime_confidence", return_value=confidence_value), \
         patch("main._compute_universal_entry_score", return_value={
             "entry_allowed": True, "score_pct": round(confidence_value * 100, 1),
             "rejection_reasons": [],
         }):
        return main._auto_signal_core(
            "TESTSTOCK.NS", currency="INR", strategy="universal_score", rr=10.0,
        )


def test_trend_regime_sizing_at_entry_score_floor_gets_the_size_floor():
    result = _run_universal_score("trend", confidence_value=main.UNIVERSAL_ENTRY_SCORE_MIN / 100.0)
    assert result["action_taken"] == "entered_long"
    assert result["confidence_sizing"]["size_multiplier"] == pytest.approx(main.CONFIDENCE_SIZE_FLOOR)


def test_trend_regime_sizing_at_full_score_gets_full_size():
    result = _run_universal_score("trend", confidence_value=1.0)
    assert result["action_taken"] == "entered_long"
    assert result["confidence_sizing"]["size_multiplier"] == pytest.approx(1.0)


def test_range_regime_sizing_at_entry_z_floor_gets_the_size_floor():
    entry_conf = main._norm_cdf(main.RANGE_CONFIDENCE_ENTRY_Z)
    result = _run_universal_score("range", confidence_value=entry_conf)
    assert result["action_taken"] == "entered_long"
    assert result["confidence_sizing"]["size_multiplier"] == pytest.approx(main.CONFIDENCE_SIZE_FLOOR)


def test_range_regime_sizing_at_full_z_gets_full_size():
    full_conf = main._norm_cdf(main.RANGE_CONFIDENCE_FULL_Z)
    result = _run_universal_score("range", confidence_value=full_conf)
    assert result["action_taken"] == "entered_long"
    assert result["confidence_sizing"]["size_multiplier"] == pytest.approx(1.0)


# ---- Integration: RANGE confidence-decay exit ------------------------------

def _insert_range_position(conn, symbol="TESTSTOCK.NS"):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, entry_regime) "
        "VALUES (?, '2026-09-09', 'long', 100.0, 90.0, 90.0, 130.0, 10, ?, 1.0, '5m', 'range')",
        (symbol, main.time.time()),
    )
    conn.commit()


def _run_range_exit_check(confidence_now):
    _fresh_db()
    fixture = _bullish_engulfing_fixture()
    with closing(main.get_db()) as conn:
        _insert_range_position(conn)
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("main._range_regime_confidence", return_value=confidence_now), \
         patch("kotak_live_feed.get_live_ticks", return_value={}):
        return main._auto_signal_core(
            "TESTSTOCK.NS", currency="INR", strategy="universal_score", rr=10.0,
            max_hold_minutes=100000.0,
        )


def test_range_position_exits_when_confidence_decays_below_the_entry_bar():
    decayed = main._norm_cdf(main.RANGE_CONFIDENCE_ENTRY_Z) - 0.05
    result = _run_range_exit_check(decayed)
    assert result["action_taken"] == "exited_range_confidence_weakened"


def test_range_position_holds_while_confidence_stays_at_or_above_the_entry_bar():
    still_extreme = main._norm_cdf(main.RANGE_CONFIDENCE_FULL_Z)
    result = _run_range_exit_check(still_extreme)
    assert result["action_taken"] != "exited_range_confidence_weakened"
