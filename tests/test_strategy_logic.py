"""
Local regression net for main.py's pure-logic functions, built BEFORE the
docs/PROJECT_STRUCTURE_PLAN.md Phase 1 module split, specifically so that
split has something to run against instead of relying on a live curl to
production (this project's only validation method until now - see
PROJECT_STRUCTURE_PLAN.md #3.3).

Deliberately scoped to functions whose expected output can be hand-verified
exactly (worked the arithmetic by hand in each test's comment) rather than
guessed - a wrong assertion is worse than no test. Two real, currently-live
strategies are covered directly: `sma_crossover` (deploy-gate's own
flagged-not-robust one) and `vwap_reclaim` (this session's VWAP work,
including its per-day `groupby(day)` logic, which is exactly the kind of
thing a mechanical code-move refactor could subtly break).

`orb_breakout` (the strategy actually live in WATCHLIST) is deliberately
NOT hand-fixture-tested here - deploy-gate.yml's own backtest regression
check already replays it against 59 days of real market data across a
12-symbol sample, which is stronger evidence than a small hand-built
fixture would be. Duplicating that here would add a second, weaker check
without adding real coverage.

Run: pytest tests/ -v  (needs pytest - see requirements-dev.txt)
"""
import math

import pandas as pd
import pytest

import main


# ---------------------------------------------------------------------------
# _norm_cdf / bs_price - Black-Scholes primitives (main.py:1085, :1089-ish
# pre-refactor; will move to options_pricing.py in Phase 1)
# ---------------------------------------------------------------------------

def test_norm_cdf_known_points():
    assert main._norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert main._norm_cdf(10.0) == pytest.approx(1.0, abs=1e-9)
    assert main._norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-9)


def test_bs_price_matches_textbook_reference():
    # Classic Hull textbook example: S=100, K=100, T=1y, r=5%, sigma=20%.
    # Hand-worked: d1 = (ln(1) + (0.05 + 0.02)) / 0.2 = 0.35, d2 = 0.15
    # N(d1) ~= 0.6368, N(d2) ~= 0.5596
    # call = 100*0.6368 - 100*e^-0.05*0.5596 ~= 10.45
    # put  = call - S + K*e^-rT ~= 5.57 (put-call parity)
    # bs_price's option_type convention is "C"/"P" (verified against source -
    # NOT the NSE "CE"/"PE" convention used elsewhere in this codebase for
    # trading-symbol strings; passing "CE" here would silently fall through
    # to the put branch, since the function only special-cases "C").
    call = main.bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="C")
    put = main.bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="P")
    assert call == pytest.approx(10.4506, abs=0.01)
    assert put == pytest.approx(5.5735, abs=0.01)
    # Put-call parity must hold exactly regardless of the reference values above.
    assert call - put == pytest.approx(100 - 100 * math.exp(-0.05 * 1.0), abs=1e-6)


def test_bs_price_zero_time_falls_back_to_intrinsic():
    # At/after expiry, an option is worth exactly its intrinsic value - no
    # time value left, matches the function's own documented fallback.
    assert main.bs_price(S=110, K=100, T=0, r=0.05, sigma=0.2, option_type="C") == pytest.approx(10.0)
    assert main.bs_price(S=90, K=100, T=0, r=0.05, sigma=0.2, option_type="C") == pytest.approx(0.0)
    assert main.bs_price(S=90, K=100, T=0, r=0.05, sigma=0.2, option_type="P") == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# extract_trades_fast - vectorized entry/exit/PnL extraction (main.py:766;
# will move to strategies.py in Phase 1)
# ---------------------------------------------------------------------------

def test_extract_trades_fast_closed_and_open_positions():
    import numpy as np

    # long flags:      F     T     T     F     T     F
    # bar index:        0     1     2     3     4     5
    # -> entry@1 (F->T), exit@3 (T->F), entry@4 (F->T), exit@5 (T->F)
    long_arr = np.array([False, True, True, False, True, False])
    close_arr = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    dates = np.array([f"2026-01-0{i+1}" for i in range(6)])
    qty = 2.0

    trades, open_position = main.extract_trades_fast(long_arr, close_arr, dates, qty)

    assert len(trades) == 2
    assert trades[0]["entry_price"] == 11.0 and trades[0]["exit_price"] == 13.0
    assert trades[0]["pnl"] == pytest.approx((13.0 - 11.0) * qty)
    assert trades[1]["entry_price"] == 14.0 and trades[1]["exit_price"] == 15.0
    assert trades[1]["pnl"] == pytest.approx((15.0 - 14.0) * qty)
    assert open_position is None  # every entry closed - no dangling position


def test_extract_trades_fast_leaves_position_open():
    import numpy as np

    # long flags: F T T  (entry@1, never exits)
    long_arr = np.array([False, True, True])
    close_arr = np.array([10.0, 11.0, 12.0])
    dates = np.array(["2026-01-01", "2026-01-02", "2026-01-03"])
    qty = 3.0

    trades, open_position = main.extract_trades_fast(long_arr, close_arr, dates, qty)

    assert trades == []
    assert open_position is not None
    assert open_position["entry_price"] == 11.0
    assert open_position["current_price"] == 12.0
    assert open_position["unrealized_pnl"] == pytest.approx((12.0 - 11.0) * qty)


# ---------------------------------------------------------------------------
# add_strategy_signal - the strategy library (main.py:435; will move to
# strategies.py in Phase 1)
# ---------------------------------------------------------------------------

def test_sma_crossover_signal_matches_hand_computed_crossover():
    # Close = [10,10,10,20,20,20,20], fast=2, slow=3.
    # fast_ma = rolling(2).mean() = [nan,10,10,15,20,20,20]
    # slow_ma = rolling(3).mean() = [nan,nan,10,13.33,16.67,20,20]
    # long = fast_ma > slow_ma (NaN compares False) ->
    #        [F, F, F(10>10 is False), T(15>13.33), T(20>16.67), F(20>20), F(20>20)]
    closes = [10, 10, 10, 20, 20, 20, 20]
    df = pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "Open": closes, "High": closes, "Low": closes, "Close": closes,
        "Volume": [100] * len(closes),
    })
    out = main.add_strategy_signal(df, "sma_crossover", {"fast": 2, "slow": 3})
    assert out["long"].tolist() == [False, False, False, True, True, False, False]


def test_vwap_reclaim_signal_matches_hand_computed_vwap():
    # Single day, 3 bars, all in Asia/Kolkata (tz-aware, so the function's
    # own tz_convert is a no-op - keeps the fixture simple).
    #  bar0: H=10 L=8  C=9  V=100 -> typical=9.0,  vwap=9.0     -> 9>9    False
    #  bar1: H=12 L=10 C=11 V=100 -> typical=11.0, vwap=10.0    -> 11>10  True
    #  bar2: H=9  L=7  C=8  V=100 -> typical=8.0,  vwap=9.333.. -> 8>9.33 False
    # raw = [F, T, F]; long = per-day cummax(raw) = [F, T, T]
    dates = pd.to_datetime([
        "2026-01-05 09:15", "2026-01-05 09:20", "2026-01-05 09:25",
    ]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({
        "Date": dates,
        "High": [10, 12, 9], "Low": [8, 10, 7], "Close": [9, 11, 8],
        "Open": [9, 11, 8], "Volume": [100, 100, 100],
    })
    out = main.add_strategy_signal(df, "vwap_reclaim", {})
    assert out["long"].tolist() == [False, True, True]
    assert out["vwap"].tolist() == pytest.approx([9.0, 10.0, 9.0 + 1 / 3], abs=1e-6)


def test_orb_breakout_ma_type_ema_matches_pandas_ewm_and_differs_from_sma():
    # 2026-09-08, explicit user instruction: "have you replaced sma with
    # ema? ema are more reliable. do your research and do the needful" -
    # orb_breakout's own trend filter was hardcoded to SMA regardless of
    # the ma_type opt-in already wired into the live trend-confidence
    # gate elsewhere; this confirms the new wiring actually switches the
    # entry-trigger computation, not just that pandas.ewm itself works
    # (trusted library code, not re-derived by hand here).
    closes = [10, 12, 11, 15, 20, 18, 25, 30, 100, 60]
    df_base = pd.DataFrame({
        "Date": pd.date_range("2026-01-01 09:15", periods=len(closes), freq="5min", tz="Asia/Kolkata"),
        "Open": closes, "High": closes, "Low": closes, "Close": closes,
        "Volume": [1000] * len(closes),
    })
    params = {"orb_minutes": 5, "sma_fast": 2, "sma_slow": 3, "open_min": 9 * 60 + 15}

    out_sma = main.add_strategy_signal(df_base.copy(), "orb_breakout", {**params, "ma_type": "sma"})
    out_ema = main.add_strategy_signal(df_base.copy(), "orb_breakout", {**params, "ma_type": "ema"})

    expected_fast_ema = pd.Series(closes, dtype=float).ewm(span=2, adjust=False).mean()
    expected_slow_ema = pd.Series(closes, dtype=float).ewm(span=3, adjust=False).mean()
    assert out_ema["fast_ma"].tolist() == pytest.approx(expected_fast_ema.tolist(), abs=1e-9)
    assert out_ema["slow_ma"].tolist() == pytest.approx(expected_slow_ema.tolist(), abs=1e-9)
    # SMA (rolling mean) and EMA (exponentially-weighted) are mathematically
    # different formulas - on this deliberately spiky fixture (a 100 spike
    # then a drop to 60) they must disagree somewhere, proving ma_type
    # actually changed which formula ran, not just that both produced
    # SOME numbers.
    assert out_sma["fast_ma"].tolist() != pytest.approx(out_ema["fast_ma"].tolist(), abs=1e-9)


def _wyckoff_fixture():
    # 23 bars, range_lookback=10 (small, so the fixture stays hand-
    # verifiable), one calendar day (Asia/Kolkata, tz-aware so the
    # function's own tz_convert is a no-op - same simplification the VWAP
    # fixture above uses).
    #
    # Bars 0-19 (20 bars): flat baseline, Close=100 High=101 Low=99 Vol=100.
    #   - warms up both rolling(10) (range) and rolling(20) (volume avg).
    # Bar 20 (the Spring): Close=99.5 High=101 Low=98.0 Vol=200.
    #   range_high[20]=max(High[10:20])=101, range_low[20]=min(Low[10:20])=99
    #   range width = (101-99)/100 = 2% <= 3% -> is_range[20]=True
    #   Low[20]=98.0 < range_low[20]*(1-0.005)=98.505 -> pierced
    #   Close[20]=99.5 > range_low[20]=99 -> closed back inside
    #   vol_avg[20]=mean(Vol[0:20])=100, 200 > 100*1.5=150 -> volume confirms
    #   => spring[20] = True
    # Bar 21 (hold): Close=100.5 High=101 Low=99.5 Vol=100.
    #   range_low[21]=min(Low[11:21])=min(99*9, 98.0)=98.0 (bar 20's own
    #   wick now enters the window) - Close[21]=100.5 is still > 98.0, so
    #   the spring's hold is NOT invalidated.
    # Bar 22 (the SOS breakout): Close=102 High=102.5 Low=100 Vol=300.
    #   range_high[22]=max(High[12:22])=101, so Close[22]=102 > 101
    #   vol_avg[22]=mean(Vol[2:22])=(18*100+200+100)/20=105, 300>105*1.5=157.5
    #   spring_seen[22]=valid_spring_active[21]=True (never invalidated)
    #   => breakout[22] = True
    n_base = 20
    closes = [100.0] * n_base + [99.5, 100.5, 102.0]
    highs = [101.0] * n_base + [101.0, 101.0, 102.5]
    lows = [99.0] * n_base + [98.0, 99.5, 100.0]
    vols = [100.0] * n_base + [200.0, 100.0, 300.0]
    dates = pd.date_range("2026-01-05 09:15", periods=len(closes), freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": vols,
    })


def test_wyckoff_spring_signal_matches_hand_computed_range_and_spring():
    df = _wyckoff_fixture()
    out = main.add_strategy_signal(df, "wyckoff_spring", {"range_lookback": 10})
    assert out["long"].tolist() == [False] * 20 + [True, True, True]


def test_wyckoff_sos_signal_matches_hand_computed_breakout():
    df = _wyckoff_fixture()
    out = main.add_strategy_signal(df, "wyckoff_sos", {"range_lookback": 10})
    assert out["long"].tolist() == [False] * 22 + [True]


def test_wyckoff_sos_requires_a_prior_spring_not_a_bare_breakout():
    # Same breakout bar (Close/High/Low/Volume unchanged) but with the
    # spring bar's Low/Volume replaced by baseline values, so no spring
    # ever fires - the SOS breakout must NOT trigger without one, even
    # though the price/volume breakout condition alone is still met.
    df = _wyckoff_fixture()
    df.loc[20, "Low"] = 99.0
    df.loc[20, "Volume"] = 100.0
    out = main.add_strategy_signal(df, "wyckoff_sos", {"range_lookback": 10})
    assert not out["long"].any(), "a bare breakout with no prior spring must not fire wyckoff_sos"


def test_vsa_climax_reversal_matches_hand_computed_climax_and_invalidation():
    # docs/STRATEGY_LOG.md #39. 18 bars, avg_lookback=10, decline_lookback=5.
    # Bars 0-9 (10): baseline warmup, Close=100 High=101 Low=99 (spread=2) Vol=100.
    # Bars 10-14 (5): decline, Close=98,96,94,92,90 (High=Close+1,Low=Close-1,
    #   spread=2), Vol=100 - establishes prior_decline for bar 15
    #   (Close[15] < Close[15-5]=Close[10]=98) and keeps spread/vol baseline
    #   unchanged for the rolling(10) averages.
    # Bar 15 (the climax): Close=88 High=92 Low=80 (spread=12) Vol=300.
    #   vol_avg[15] = mean(Vol[5:15]) = 100 (all baseline/decline bars are
    #   100) -> 300 > 100*2.0=200 (climax_volume_mult) -> volume confirms
    #   spread_avg[15] = mean(spread[5:15]) = 2 -> 12 > 2*1.5=3 (climax_spread_mult)
    #   close_position[15] = (88-80)/(92-80) = 0.667 >= 0.5 (climax_close_pct)
    #   prior_decline[15]: Close[15]=88 < Close[10]=98 -> True
    #   => climax[15] = True
    # Bar 16 (hold): Close=90 > climax_low(80) -> still holding.
    # Bar 17 (invalidated): Close=78 < climax_low(80) -> holding ends, False.
    closes = [100.0] * 10 + [98.0, 96.0, 94.0, 92.0, 90.0] + [88.0, 90.0, 78.0]
    highs = [101.0] * 10 + [99.0, 97.0, 95.0, 93.0, 91.0] + [92.0, 91.0, 79.0]
    lows = [99.0] * 10 + [97.0, 95.0, 93.0, 91.0, 89.0] + [80.0, 89.0, 77.0]
    vols = [100.0] * 15 + [300.0, 100.0, 100.0]
    dates = pd.date_range("2026-01-05 09:15", periods=len(closes), freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "Date": dates, "Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": vols,
    })
    params = {
        "avg_lookback": 10, "decline_lookback": 5, "climax_volume_mult": 2.0,
        "climax_spread_mult": 1.5, "climax_close_pct": 0.5,
    }
    out = main.add_strategy_signal(df, "vsa_climax_reversal", params)
    assert out["long"].tolist() == [False] * 15 + [True, True, False]


def test_orb_breakout_vsa_filter_suppresses_a_no_demand_trigger_bar():
    # docs/STRATEGY_LOG.md #38. 21 bars, orb_minutes=5 (only bar 0, at
    # 09:15, is inside the ORB window) -> orb_high = High[0] = 101, held
    # for the rest of the day. Bars 1-19 (19 bars, flat baseline Close=100
    # High=101 Low=99 spread=2 Vol=1000) warm up the vsa_filter's own
    # rolling(20) spread/volume averages (rolling(20).shift(1) at bar 20
    # needs exactly bars 0-19). Bar 20 is a "No Demand" trigger bar: an UP
    # bar (Close=101.2 > Open=101.1, and > orb_high=101, so the plain
    # breakout condition IS met) with a narrow spread (0.3 < 2*0.7=1.4)
    # and low volume (500 < 1000*0.7=700) - the classic weak-rally tell.
    n_base = 20
    closes = [100.0] * n_base + [101.2]
    opens = [100.0] * n_base + [101.1]
    highs = [101.0] * n_base + [101.3]
    lows = [99.0] * n_base + [101.0]
    vols = [1000.0] * n_base + [500.0]
    dates = pd.date_range("2026-01-05 09:15", periods=len(closes), freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "Date": dates, "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols,
    })
    params = {"orb_minutes": 5, "sma_fast": 2, "sma_slow": 3, "open_min": 9 * 60 + 15}

    out_default = main.add_strategy_signal(df.copy(), "orb_breakout", params)
    assert bool(out_default["long"].iloc[20]) is True, \
        "vsa_filter defaults to False - a No Demand trigger bar must still fire, unchanged behavior"

    out_filtered = main.add_strategy_signal(df.copy(), "orb_breakout", {**params, "vsa_filter": True})
    assert bool(out_filtered["long"].iloc[20]) is False, \
        "vsa_filter=True must suppress a breakout triggered by a No Demand bar"


def test_unsupported_strategy_raises():
    df = pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=2, freq="D"),
        "Open": [1, 1], "High": [1, 1], "Low": [1, 1], "Close": [1, 1], "Volume": [1, 1],
    })
    with pytest.raises(Exception):
        main.add_strategy_signal(df, "not_a_real_strategy", {})


# ---------------------------------------------------------------------------
# TODO (Phase 1 follow-up, noted in PROJECT_STRUCTURE_PLAN.md #3.2): the
# risk_amount_inr = usable_capital_inr * risk_per_trade_pct / 100 sizing
# formula is duplicated inline in _auto_signal_core and _options_signal_core
# rather than being its own function - nothing to unit-test here yet without
# duplicating that inline expression by hand. Extract it to a real helper as
# part of Phase 1, then add its test here.
# ---------------------------------------------------------------------------
