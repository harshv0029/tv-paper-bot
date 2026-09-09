"""Tests for the universal multi-factor entry-confidence engine (2026-09-09
architecture revamp - explicit user instruction: "revamp all of the strategy
architecture from beginning"). Covers the new pure functions
(_compute_universal_entry_score, _compute_target_cluster, _split_exit_legs,
_next_unfilled_leg, and their small building blocks) plus the staged
profit-booking DB primitive (_execute_staged_leg_exit), the same way
test_trailing_stop_fixed_gap.py/test_real_position_scheduler_visibility.py
already test this file's other risk/exit machinery - hand-verified fixtures,
not live network calls."""
import json
import os
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- _split_exit_legs -------------------------------------------------------

def test_split_exit_legs_qty_zero_or_negative_is_empty():
    assert main._split_exit_legs(0, {}) == []
    assert main._split_exit_legs(-3, {}) == []


def test_split_exit_legs_qty_one_is_a_single_trail_leg_no_staging():
    legs = main._split_exit_legs(1, {"1.0R": 100.0})
    assert legs == [{"leg": "trail", "qty": 1, "r_multiple": None, "target_price": None, "status": "open"}]


def test_split_exit_legs_qty_two_is_two_legs_one_to_one():
    legs = main._split_exit_legs(2, {"1.0R": 100.0})
    assert [l["leg"] for l in legs] == ["T1", "trail"]
    assert [l["qty"] for l in legs] == [1, 1]
    assert legs[0]["target_price"] == 100.0
    assert legs[1]["target_price"] is None


def test_split_exit_legs_qty_three_is_three_legs_one_to_one_to_one():
    legs = main._split_exit_legs(3, {"1.0R": 100.0, "1.5R": 105.0})
    assert [l["leg"] for l in legs] == ["T1", "T2", "trail"]
    assert [l["qty"] for l in legs] == [1, 1, 1]


def test_split_exit_legs_qty_four_is_classic_25_25_25_trail():
    legs = main._split_exit_legs(4, {"1.0R": 100.0, "1.5R": 105.0, "2.0R": 110.0})
    assert [l["leg"] for l in legs] == ["T1", "T2", "T3", "trail"]
    assert [l["qty"] for l in legs] == [1, 1, 1, 1]


def test_split_exit_legs_remainder_absorbed_by_trail_leg():
    # qty=7: base = 7//4 = 1 per fixed leg, trail absorbs the remainder (4).
    legs = main._split_exit_legs(7, {"1.0R": 100.0, "1.5R": 105.0, "2.0R": 110.0})
    qtys = {l["leg"]: l["qty"] for l in legs}
    assert qtys == {"T1": 1, "T2": 1, "T3": 1, "trail": 4}
    assert sum(qtys.values()) == 7


def test_split_exit_legs_large_qty_splits_evenly():
    legs = main._split_exit_legs(100, {"1.0R": 100.0, "1.5R": 105.0, "2.0R": 110.0})
    qtys = {l["leg"]: l["qty"] for l in legs}
    assert qtys == {"T1": 25, "T2": 25, "T3": 25, "trail": 25}


# ---- _next_unfilled_leg -----------------------------------------------------

def test_next_unfilled_leg_none_when_no_ladder():
    assert main._next_unfilled_leg(None) is None
    assert main._next_unfilled_leg("") is None


def test_next_unfilled_leg_skips_trail_and_filled_legs():
    legs = main._split_exit_legs(4, {"1.0R": 100.0, "1.5R": 105.0, "2.0R": 110.0})
    legs[0]["status"] = "filled"
    nxt = main._next_unfilled_leg(json.dumps(legs))
    assert nxt["leg"] == "T2"


def test_next_unfilled_leg_none_when_only_trail_remains():
    legs = main._split_exit_legs(2, {"1.0R": 100.0})
    legs[0]["status"] = "filled"
    assert main._next_unfilled_leg(json.dumps(legs)) is None


# ---- _compute_target_cluster ------------------------------------------------

def _flat_high_low_close_df(n=40, start=100.0, end=120.0):
    return pd.DataFrame({
        "High": np.linspace(start, end, n) + 0.5,
        "Low": np.linspace(start, end, n) - 0.5,
        "Close": np.linspace(start, end, n),
    })


def test_compute_target_cluster_invalid_risk_falls_back_to_plain_rr():
    df = _flat_high_low_close_df()
    out = main._compute_target_cluster(100.0, 100.0, df, rr=3.0)  # stop == entry -> r<=0
    assert out["primary_target"] == 100.0  # entry + 3*0
    assert out["confidence"] is None


def test_compute_target_cluster_r_multiples_are_correct():
    df = _flat_high_low_close_df()
    out = main._compute_target_cluster(120.0, 118.0, df, rr=3.0)
    assert out["r_multiples"]["1.0R"] == 122.0
    assert out["r_multiples"]["2.0R"] == 124.0
    assert out["r_multiples"]["3.0R"] == 126.0


def test_compute_target_cluster_primary_target_is_a_real_number_with_history():
    df = _flat_high_low_close_df()
    out = main._compute_target_cluster(120.0, 118.0, df, rr=3.0)
    assert out["primary_target"] > 120.0
    assert out["atr_target"] is not None


# ---- ATR / RSI / VWAP / structure building blocks --------------------------

def test_atr_value_positive_for_a_trending_series():
    df = _flat_high_low_close_df()
    val = main._compute_atr_value(df)
    assert val is not None and val > 0


def test_atr_value_none_for_too_short_a_series():
    df = _flat_high_low_close_df(n=5)
    assert main._compute_atr_value(df) is None


def test_rsi_value_high_for_a_strictly_rising_series():
    closes = np.linspace(100, 130, 30)
    rsi = main._compute_rsi_value(closes)
    assert rsi is not None and rsi > 90  # every bar is a gain, RSI should be near 100


def test_rsi_value_none_when_not_enough_history():
    assert main._compute_rsi_value(np.array([100.0, 101.0])) is None


def test_session_vwap_none_on_zero_volume_session():
    # Yahoo's own index-ticker quirk (volume:0 on every bar) - see
    # docs/STRATEGY_LOG.md rows #13-18's own caveat, same root cause.
    today_df = pd.DataFrame({"High": [10, 11], "Low": [9, 10], "Close": [9.5, 10.5], "Volume": [0, 0]})
    assert main._compute_session_vwap_value(today_df) is None


def test_session_vwap_real_value_with_real_volume():
    today_df = pd.DataFrame({"High": [10, 11], "Low": [9, 10], "Close": [9.5, 10.5], "Volume": [100, 200]})
    vwap = main._compute_session_vwap_value(today_df)
    assert vwap is not None and 9.5 < vwap < 10.5


def test_swing_structure_bullish_true_for_a_clean_uptrend():
    df = _flat_high_low_close_df(n=40)
    assert main._swing_structure_bullish(df) is True


def test_swing_structure_bullish_none_when_not_enough_history():
    df = _flat_high_low_close_df(n=10)
    assert main._swing_structure_bullish(df) is None


def test_relative_strength_bullish_true_when_symbol_outperforms_index():
    sym = np.linspace(100, 130, 25)   # +30%
    idx = np.linspace(100, 105, 25)   # +5%
    assert main._relative_strength_bullish(sym, idx) is True


def test_relative_strength_bullish_false_when_symbol_underperforms_index():
    sym = np.linspace(100, 102, 25)   # +2%
    idx = np.linspace(100, 130, 25)   # +30%
    assert main._relative_strength_bullish(sym, idx) is False


def test_index_trend_bullish_true_for_a_rising_index():
    idx = np.linspace(100, 130, 30)
    assert main._index_trend_bullish(idx, 9, 21, "ema") is True


# ---- _compute_universal_entry_score ----------------------------------------

def _bullish_fixture(n=60):
    df = pd.DataFrame({
        "High": np.linspace(100, 130, n) + 0.5,
        "Low": np.linspace(100, 130, n) - 0.5,
        "Close": np.linspace(100, 130, n),
        "Volume": np.concatenate([np.full(n - 1, 1000.0), [3000.0]]),
    })
    today_df = df.iloc[-5:].copy()
    closes = df["Close"].to_numpy()
    sma_f = main._moving_average(closes, 9, "ema")
    sma_s = main._moving_average(closes, 21, "ema")
    return df, today_df, sma_f, sma_s


def test_universal_entry_score_high_for_a_clean_uptrend_with_index():
    df, today_df, sma_f, sma_s = _bullish_fixture()
    index_closes = np.linspace(200, 210, 60)  # bullish index too
    # vol_ratio=2.0 (exceptional RVOL) - see the 2026-09-10 volume
    # double-counting fix: volume_breakout now needs a real RVOL reading
    # to score at all, separate from the volume_ok gate boolean.
    out = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, index_closes, 9, 21, "ema", vol_ratio=2.0,
    )
    assert out["max_score"] == 100
    assert out["score_pct"] >= main.UNIVERSAL_ENTRY_SCORE_MIN
    assert out["entry_allowed"] is True
    assert out["rejection_reasons"] == []


def test_universal_entry_score_renormalizes_when_no_index_reference():
    df, today_df, sma_f, sma_s = _bullish_fixture()
    out = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0,
    )
    assert out["max_score"] == 80  # relative_strength + index_trend (20pts) dropped
    assert "relative_strength" not in out["breakdown"]
    assert "index_trend" not in out["breakdown"]


def test_universal_entry_score_max_score_also_drops_a_none_non_index_component():
    # 2026-09-10 fix: max_score used to only ever shrink for the two
    # index-dependent components - any of the other 6 coming back None
    # (no vol_ratio here) left max_score unfairly high. Every None
    # component must drop from max_score, not just the index-dependent
    # ones.
    df, today_df, sma_f, sma_s = _bullish_fixture()
    with_vol = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0,
    )
    without_vol = main._compute_universal_entry_score(
        df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=None,
    )
    assert without_vol["breakdown"]["volume_breakout"] is None
    assert without_vol["max_score"] == with_vol["max_score"] - main.UNIVERSAL_SCORE_WEIGHTS["volume_breakout"]


def test_universal_entry_score_rejects_on_thin_liquidity():
    df, today_df, sma_f, sma_s = _bullish_fixture()
    out = main._compute_universal_entry_score(df, today_df, False, sma_f, sma_s, None, 9, 21, "ema")
    assert "liquidity_inadequate" in out["rejection_reasons"]
    assert out["entry_allowed"] is False  # rejection filter overrides score alone


def test_universal_entry_score_never_raises_on_a_too_short_history():
    df = pd.DataFrame({"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [500.0]})
    # volume_ok=False here (not just a short df) so this also exercises the
    # "score 0, nothing else computable" floor cleanly - the point of this
    # test is that a 1-row frame never raises, not any particular score.
    out = main._compute_universal_entry_score(df, df, False, None, None, None, 9, 21, "ema")
    assert out["entry_allowed"] is False  # nothing computable -> score 0, never crashes
    assert out["score"] == 0
    assert out["breakdown"]["ema_cross"] is None  # sma_fast_val/sma_slow_val were None
    assert out["breakdown"]["rsi_band"] is None   # not enough closes for RSI
    assert out["breakdown"]["structure_hh_hl"] is None  # not enough bars for structure


# ---- _execute_staged_leg_exit (DB-backed) -----------------------------------

def _insert_open_signal_state(conn, symbol="TCS.NS", entry_price=100.0, qty=8, exit_legs=None):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, "
        "target, qty, entry_ts, fx_to_inr, interval, exit_legs_json) "
        "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, 1.0, '5m', ?)",
        (symbol, main.ist_now().strftime("%Y-%m-%d"), entry_price, entry_price - 2, entry_price - 2,
         entry_price + 6, qty, main.time.time(), json.dumps(exit_legs) if exit_legs else None),
    )
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, ?, 'buy', ?, ?, 1.0, ?, '{}')",
        (main.time.time(), symbol, qty, entry_price, f"{main.ORB_STRATEGY_PREFIX}universal-score"),
    )
    conn.commit()


def test_execute_staged_leg_exit_books_partial_qty_and_keeps_position_open():
    _fresh_db()
    legs = main._split_exit_legs(8, {"1.0R": 102.0, "1.5R": 103.0, "2.0R": 104.0})
    with closing(main.get_db()) as conn:
        _insert_open_signal_state(conn, qty=8, exit_legs=legs)
        booking = main._execute_staged_leg_exit(conn, "TCS.NS", "T1", 2, 102.5, 100.0, 1.0)
        assert booking["booked"] is True
        assert booking["remaining_qty"] == 6

        row = conn.execute("SELECT * FROM signal_state WHERE symbol = 'TCS.NS'").fetchone()
        assert row is not None, "position must stay open - only a partial qty booked"
        assert row["qty"] == 6
        stored_legs = json.loads(row["exit_legs_json"])
        t1 = next(l for l in stored_legs if l["leg"] == "T1")
        assert t1["status"] == "filled"

        sell_rows = conn.execute(
            "SELECT * FROM trades WHERE symbol='TCS.NS' AND action='sell'"
        ).fetchall()
        assert len(sell_rows) == 1
        payload = json.loads(sell_rows[0]["raw_payload"])
        assert payload["exit_reason"] == "staged_leg_T1"
        assert payload["qty"] == 2


def test_execute_staged_leg_exit_closes_position_when_it_drains_the_remaining_qty():
    _fresh_db()
    legs = main._split_exit_legs(1, {})  # single trail leg, qty=1
    with closing(main.get_db()) as conn:
        _insert_open_signal_state(conn, qty=1, exit_legs=legs)
        booking = main._execute_staged_leg_exit(conn, "TCS.NS", "trail", 1, 105.0, 100.0, 1.0)
        assert booking["booked"] is True
        assert booking["remaining_qty"] == 0
        row = conn.execute("SELECT * FROM signal_state WHERE symbol = 'TCS.NS'").fetchone()
        assert row is None  # fully closed


def test_execute_staged_leg_exit_returns_not_booked_when_no_open_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        booking = main._execute_staged_leg_exit(conn, "NOPOS.NS", "T1", 1, 100.0, 100.0, 1.0)
        assert booking == {"booked": False}
