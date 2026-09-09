"""Tests for the two-regime router (2026-09-10) - explicit user decision:
"Option B - but only the two-regime version" after the #1/#9 discussion
found the universal score structurally rejects VWAP mean reversion (the
one strategy in the whole docs/STRATEGY_LOG.md catalog with real
positive gross backtest evidence). _classify_market_regime gates the
existing trend engine behind TREND/RANGE; RANGE routes to
_vwap_mean_reversion_entry (the live single-tick version of
add_strategy_signal's own "vwap_mean_reversion" strategy, row #13)."""
import numpy as np
import pandas as pd

import main


def _clean_uptrend(n=60):
    return pd.DataFrame({
        "High": np.linspace(100, 130, n) + 0.5,
        "Low": np.linspace(100, 130, n) - 0.5,
        "Close": np.linspace(100, 130, n),
        "Volume": np.concatenate([np.full(n - 1, 1000.0), [3000.0]]),
    })


def _ranging_with_a_sharp_dip(n=60):
    # Oscillates around 100 with no sustained trend, then a sharp one-bar
    # dip on the last bar - the exact fixture that proved AND (not OR) is
    # needed in _classify_market_regime: a single big bar alone spikes
    # _trend_confidence without any real higher-high/higher-low structure
    # behind it.
    close = np.sin(np.linspace(0, 6 * np.pi, n)) * 2.0 + 100.0
    close = close.copy()
    close[-1] = 96.0
    return pd.DataFrame({"High": close + 0.3, "Low": close - 0.3, "Close": close, "Volume": np.full(n, 1000.0)})


# ---- _classify_market_regime ------------------------------------------------

def test_classify_market_regime_clean_uptrend_is_trend():
    df = _clean_uptrend()
    assert main._classify_market_regime(df, 9, 21, "ema") == "trend"


def test_classify_market_regime_ranging_with_one_sharp_bar_is_range_not_trend():
    # The whole point of requiring AND, not OR: a one-bar statistical
    # spike alone must never be enough to call this TREND.
    df = _ranging_with_a_sharp_dip()
    assert main._classify_market_regime(df, 9, 21, "ema") == "range"


def test_classify_market_regime_defaults_to_range_on_short_history():
    df = _clean_uptrend(n=10)  # too short for sma_slow=21 -> trend_conf 0.0, structure None
    assert main._classify_market_regime(df, 9, 21, "ema") == "range"


# ---- _vwap_mean_reversion_entry ---------------------------------------------

def test_vwap_mean_reversion_entry_fires_on_a_real_dip_below_the_lower_band():
    df = _ranging_with_a_sharp_dip()
    today_df = df.iloc[-20:].copy()
    assert main._vwap_mean_reversion_entry(today_df) is True


def test_vwap_mean_reversion_entry_false_for_a_clean_uptrend_no_dip():
    df = _clean_uptrend()
    today_df = df.iloc[-20:].copy()
    assert main._vwap_mean_reversion_entry(today_df) is False


def test_vwap_mean_reversion_entry_none_on_zero_volume_session():
    today_df = pd.DataFrame({"High": [10, 11], "Low": [9, 10], "Close": [9.5, 10.5], "Volume": [0, 0]})
    assert main._vwap_mean_reversion_entry(today_df) is None


def test_vwap_mean_reversion_entry_none_with_fewer_than_two_bars():
    today_df = pd.DataFrame({"High": [10], "Low": [9], "Close": [9.5], "Volume": [100]})
    assert main._vwap_mean_reversion_entry(today_df) is None


# ---- the worked example from the #1/#9 discussion, end to end -------------

def test_the_original_mean_reversion_example_now_reaches_a_real_entry_trigger():
    # This is the exact scenario the #1/#9 discussion used to show the
    # trend engine structurally rejects mean reversion: price ranging,
    # no sustained trend/structure, then dipping below the lower VWAP
    # band. Proves the regime router actually gives this setup a path to
    # firing, which the old single-engine design could not.
    df = _ranging_with_a_sharp_dip()
    today_df = df.iloc[-20:].copy()
    regime = main._classify_market_regime(df, 9, 21, "ema")
    assert regime == "range"
    assert main._vwap_mean_reversion_entry(today_df) is True

    closes = df["Close"].to_numpy()
    sma_f = main._moving_average(closes, 9, "ema")
    sma_s = main._moving_average(closes, 21, "ema")
    old_engine_score = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=1.0,
    )
    assert old_engine_score["entry_allowed"] is False  # the trend engine alone would still reject this
