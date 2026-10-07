"""Tests for the Order Block (delta) and Volume Profile/POC bounce live
ports (2026-10-05, explicit user instruction "make viable strategies in the
live wiring" -> "Port and real money now"). Synthetic data only - the
full-universe validation replay calling these main.py functions is still
owed (backlog B-30)."""
import numpy as np
import pandas as pd

import main


def _frame(close, open_=None, high=None, low=None, vol=None):
    close = np.asarray(close, dtype=float)
    open_ = close.copy() if open_ is None else np.asarray(open_, dtype=float)
    high = np.maximum(close, open_) + 0.5 if high is None else np.asarray(high, dtype=float)
    low = np.minimum(close, open_) - 0.5 if low is None else np.asarray(low, dtype=float)
    vol = np.full(len(close), 1000.0) if vol is None else np.asarray(vol, dtype=float)
    dates = pd.date_range("2025-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"Date": dates, "Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol})


def _order_block_fixture():
    n = 90
    close = np.full(n, 100.0)
    open_ = np.full(n, 100.0)
    high = close + 1.0
    low = close - 1.0
    vol = np.full(n, 1000.0)
    ob = 75                       # bearish candle = the order block
    open_[ob], close[ob], high[ob], low[ob] = 101.0, 99.0, 101.5, 98.5
    imp = ob + 1                  # impulse: +6% on 4x volume
    open_[imp], close[imp], high[imp], low[imp] = 99.0, 105.0, 105.5, 98.8
    vol[imp] = 4000.0
    for k in range(imp + 1, n - 1):   # hold above the block's low
        open_[k], close[k], high[k], low[k] = 106.0, 106.0, 106.8, 105.2
    t = n - 1                     # retest day: dips into block, closes bullish above its low
    open_[t], close[t], high[t], low[t] = 99.5, 101.0, 101.2, 99.0
    return _frame(close, open_, high, low, vol)


def test_order_block_entry_fires_on_delta_confirmed_retest():
    sig = main.order_block_entry_signal(_order_block_fixture())
    assert sig is not None
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_order_block_no_signal_without_buy_pressure_on_retest():
    df = _order_block_fixture()
    t = len(df) - 1
    df.loc[t, "Close"] = 99.2   # bearish retest bar -> today's delta <= 0
    df.loc[t, "Open"] = 100.5
    assert main.order_block_entry_signal(df) is None


def test_order_block_no_signal_when_zone_invalidated():
    df = _order_block_fixture()
    df.loc[80, "Close"] = 97.0   # closes below the block low before today
    assert main.order_block_entry_signal(df) is None


def test_order_block_no_signal_on_short_history():
    assert main.order_block_entry_signal(_order_block_fixture().iloc[-50:].reset_index(drop=True)) is None


def _vp_fixture():
    n = 100
    rng = np.random.default_rng(1)
    close = np.full(n, 100.0) + rng.normal(0, 0.1, n)
    close[-4:-1] = 108.0          # recently traded well above the POC band
    open_ = close.copy()
    high = close + 0.6
    low = close - 0.6
    vol = np.full(n, 1000.0)
    t = n - 1                     # bullish bounce back to the ~100 POC
    open_[t], close[t], high[t], low[t] = 99.4, 100.3, 100.8, 99.0
    return _frame(close, open_, high, low, vol)


def test_volume_profile_entry_fires_on_poc_bounce():
    sig = main.volume_profile_poc_entry_signal(_vp_fixture())
    assert sig is not None
    assert sig["stop_loss"] < sig["entry_price"]


def test_volume_profile_no_signal_without_prior_approach_from_above():
    df = _vp_fixture()
    df.loc[len(df) - 4:len(df) - 2, "Close"] = 100.0
    assert main.volume_profile_poc_entry_signal(df) is None


def test_volume_profile_no_signal_on_bearish_bar():
    df = _vp_fixture()
    t = len(df) - 1
    df.loc[t, "Open"], df.loc[t, "Close"] = 100.8, 100.3
    assert main.volume_profile_poc_entry_signal(df) is None


def test_poc_lands_on_most_traded_level():
    n = 60
    highs = np.full(n, 100.5)
    lows = np.full(n, 99.5)
    vols = np.full(n, 1000.0)
    highs[:5], lows[:5] = 120.0, 119.0   # a few thin bars far above
    poc, bw = main._compute_poc(highs, lows, vols, 0, n)
    assert 99.0 < poc < 101.5 and bw > 0


def _exit_df(last_close, n=40):
    close = np.full(n, 100.0)
    close[-1] = last_close
    return _frame(close)


def test_exits_trail_stop_and_hold_running_max():
    for fn in (main.order_block_exit_reason, main.volume_profile_poc_exit_reason):
        df = _exit_df(100.0)
        reason, rm = fn(df, "2099-01-01", 90.0, 2.0, 100.0)
        assert reason is None and rm == 100.0
        reason, _ = fn(_exit_df(85.0), "2099-01-01", 90.0, 2.0, 100.0)   # 100 - 6*2 = 88 -> hit (B-26 6.0x trail)
        assert reason == "trail_stop_hit"


def test_exits_max_hold_timeout():
    df = _exit_df(100.0, n=50)
    for fn, hold in ((main.order_block_exit_reason, main.ORDER_BLOCK_MAX_HOLD_DAYS),
                     (main.volume_profile_poc_exit_reason, main.VP_MAX_HOLD_DAYS)):
        entry_day = str(df["Date"].iloc[-1 - hold])
        reason, _ = fn(df, entry_day, 50.0, 1.0, 100.0)
        assert reason == "max_hold_timeout"


def test_tags_map_to_viable_registry_entries_and_open_real_gate():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["order_block_delta"] == "order_block_delta__retest__long__1d__trail6d0__v1"
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["volume_profile_poc"] == "volume_profile_poc__bounce__long__1d__trail6d0__v1"
    assert main._is_strategy_viable_for_real_money("order_block_delta") is True
    assert main._is_strategy_viable_for_real_money("volume_profile_poc") is True


def test_trade_thesis_entries_exist():
    for tag in ("order_block_delta", "volume_profile_poc"):
        assert tag in main._TRADE_THESIS_COMPONENTS
