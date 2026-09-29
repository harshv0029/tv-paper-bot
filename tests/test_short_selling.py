"""Tests for the RANGE-regime short-selling mirror (2026-09-29, explicit
user instruction: "Implement short selling in real money", built after
confirming with the user that a naive "TREND-down" mirror was out of
scope and the RANGE mean-reversion short (already backtested in
universal-score-range-short-research.yml) was the only strategy with any
evidence behind it. These tests cover the pure-function math mirrors
(entry trigger sign, stop/target formulas, confidence, trailing stop) and
one end-to-end DB round trip through _short_signal_core - not a full
replay of every edge case the long path's own test suite covers, matching
the deliberately-scoped-down first cut documented in main.py's own
_maybe_place_real_short_entry docstring."""
import json
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


def _today_df_above_vwap(n=30, base=100.0, spike_pct=6.0):
    """A quiet intraday session whose LAST bar spikes sharply above the
    session's own VWAP - the mirror image of test_regime_router.py's
    "ranging with a sharp dip" fixture, shaped to fire
    _vwap_mean_reversion_short_entry (close far ABOVE VWAP)."""
    rows = []
    for i in range(n - 1):
        c = base + 0.1 * np.sin(i / 3.0)
        rows.append({"Open": c, "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 1000})
    spike_close = base * (1 + spike_pct / 100)
    rows.append({"Open": base, "High": spike_close + 0.05, "Low": base - 0.1, "Close": spike_close, "Volume": 5000})
    return pd.DataFrame(rows)


def _ranging_with_a_sharp_spike(n=60):
    """Mirror of test_regime_router.py's _ranging_with_a_sharp_dip - a
    single sharp UP bar on top of an otherwise flat oscillation, so
    _classify_market_regime still reads "range" (no sustained HH/HL
    structure) rather than "trend"."""
    close = np.sin(np.linspace(0, 6 * np.pi, n)) * 2.0 + 100.0
    close = close.copy()
    close[-1] = 104.0
    return pd.DataFrame({"High": close + 0.3, "Low": close - 0.3, "Close": close, "Volume": np.full(n, 1000.0)})


# ---- _vwap_mean_reversion_short_entry ---------------------------------------

def test_short_entry_fires_on_a_sharp_spike_above_vwap():
    today_df = _today_df_above_vwap()
    z = main._vwap_deviation_z(today_df)
    assert z is not None and z < -2.0, f"fixture must produce z <= -2.0, got {z}"
    assert main._vwap_mean_reversion_short_entry(today_df) is True


def test_short_entry_does_not_fire_on_a_dip_below_vwap():
    # The LONG entry's own fixture shape (spike DOWN) must NOT fire the
    # short mirror - the two triggers must be mutually exclusive, not
    # both true on the same bar.
    today_df = _today_df_above_vwap(spike_pct=-6.0)
    assert main._vwap_mean_reversion_short_entry(today_df) is False


def test_short_entry_and_long_entry_are_mutually_exclusive():
    today_df = _today_df_above_vwap()
    assert main._vwap_mean_reversion_entry(today_df) is False
    assert main._vwap_mean_reversion_short_entry(today_df) is True


# ---- _range_regime_short_stop_loss ------------------------------------------

def test_short_stop_loss_sits_above_last_close_using_min_not_max():
    df = _today_df_above_vwap()
    last_close = float(df["Close"].iloc[-1])
    stop_loss_cap = last_close * (1 + 2.0 / 100)  # stop_pct=2.0
    stop = main._range_regime_short_stop_loss(last_close, df, stop_loss_cap)
    assert stop > last_close, "a short's stop must sit ABOVE entry, never below"
    atr_val = main._compute_atr_value(df)
    assert atr_val and atr_val > 0
    expected_atr_stop = last_close + main.RANGE_STOP_ATR_MULT * atr_val
    assert stop == min(expected_atr_stop, stop_loss_cap)


def test_short_stop_loss_never_exceeds_the_stop_pct_cap():
    df = _today_df_above_vwap()
    last_close = float(df["Close"].iloc[-1])
    tight_cap = last_close * (1 + 0.1 / 100)  # tighter than the ATR floor
    stop = main._range_regime_short_stop_loss(last_close, df, tight_cap)
    assert stop == tight_cap


# ---- _compute_target_cluster_short ------------------------------------------
# (2026-09-29 root-cause fix: range-short-validation-replay.yml's first
# full-universe run showed PFnet 0.17 / win rate 15.3% against a plain fixed
# 3R target - only 7.1% of exits were target_hit. Mirrors
# test_universal_score_engine.py's own _compute_target_cluster tests.)

def _flat_high_low_close_df_desc(n=40, start=120.0, end=100.0):
    return pd.DataFrame({
        "High": np.linspace(start, end, n) + 0.5,
        "Low": np.linspace(start, end, n) - 0.5,
        "Close": np.linspace(start, end, n),
    })


def test_compute_target_cluster_short_invalid_risk_falls_back_to_plain_rr():
    df = _flat_high_low_close_df_desc()
    out = main._compute_target_cluster_short(100.0, 100.0, df, rr=3.0)  # stop == entry -> r<=0
    assert out["primary_target"] == 100.0  # entry - 3*0
    assert out["confidence"] is None


def test_compute_target_cluster_short_r_multiples_are_correct():
    df = _flat_high_low_close_df_desc()
    out = main._compute_target_cluster_short(118.0, 120.0, df, rr=3.0)
    assert out["r_multiples"]["1.0R"] == 116.0
    assert out["r_multiples"]["2.0R"] == 114.0
    assert out["r_multiples"]["3.0R"] == 112.0


def test_compute_target_cluster_short_primary_target_is_below_entry_with_history():
    df = _flat_high_low_close_df_desc()
    out = main._compute_target_cluster_short(118.0, 120.0, df, rr=3.0)
    assert out["primary_target"] < 118.0
    assert out["atr_target"] is not None


# ---- _target_move_pct_short / _range_regime_short_confidence ---------------

def test_target_move_pct_short_positive_for_a_target_below_close():
    assert main._target_move_pct_short(target=95.0, last_close=100.0) == pytest.approx(5.0)


def test_range_regime_short_confidence_uses_negative_z():
    today_df = _today_df_above_vwap()
    z = main._vwap_deviation_z(today_df)
    conf = main._range_regime_short_confidence(today_df)
    assert conf == pytest.approx(main._norm_cdf(-z))
    assert conf >= main._norm_cdf(main.RANGE_CONFIDENCE_ENTRY_Z)


# ---- _trailing_stop_target_short --------------------------------------------

def test_short_trailing_stop_not_activated_before_half_r_favorable_move():
    df = _today_df_above_vwap()
    entry_price = 106.0
    initial_stop = 110.0  # R = 4.0, above entry for a short
    trough, candidate = main._trailing_stop_target_short(
        df, entry_price, initial_stop, entry_ts=0.0, tz_offset_min=main.IST_OFFSET_MIN,
        live_price=105.0,  # only 1.0 favorable move, < 0.5*4.0=2.0 required
    )
    assert candidate is None
    assert trough == 105.0


def test_short_trailing_stop_activates_and_trails_down_never_up():
    df = _today_df_above_vwap()
    entry_price = 106.0
    initial_stop = 110.0  # R = 4.0
    # Favorable move of 3.0 (>= 0.5*4.0=2.0) - activated.
    trough, candidate = main._trailing_stop_target_short(
        df, entry_price, initial_stop, entry_ts=0.0, tz_offset_min=main.IST_OFFSET_MIN,
        live_price=103.0, known_trough=103.0,
    )
    assert candidate is not None
    assert candidate < initial_stop, "an activated trailing stop must be tighter than the initial stop"
    assert candidate <= entry_price * (1 - main.TRAIL_BREAKEVEN_BUFFER_PCT / 100) + 1e-9, \
        "must never trail looser than the breakeven floor"

    # Price moves further favorably (trough drops) - stop must ratchet DOWN, never back up.
    trough2, candidate2 = main._trailing_stop_target_short(
        df, entry_price, initial_stop, entry_ts=0.0, tz_offset_min=main.IST_OFFSET_MIN,
        live_price=100.0, known_trough=trough,
    )
    assert candidate2 < candidate, "the short trailing stop must only ever move down (tighter), never up"


# ---- end-to-end _short_signal_core (paper only) -----------------------------

class _FakeYFinance:
    def __init__(self, df):
        self._df = df

    def __call__(self, symbol, period, interval):
        return self._df.assign(Date=pd.date_range("2026-09-29 03:45", periods=len(self._df), freq="5min", tz="UTC"))


def test_short_signal_core_enters_a_short_on_a_range_spike(monkeypatch):
    _fresh_db()
    df = _ranging_with_a_sharp_spike()
    monkeypatch.setattr(main, "fetch_ohlc", _FakeYFinance(df))
    monkeypatch.setattr(main, "get_fx_to_inr", lambda currency: 1.0)
    monkeypatch.setattr(main.sentiment_signals, "allows_entry", lambda symbol, day: (True, "no_data"))
    monkeypatch.setattr(main, "_liquidity_gate", lambda df: (True, []))
    monkeypatch.setattr(main, "_likely_lower_circuit_locked", lambda df, today_str: False)

    result = main._short_signal_core(
        symbol="TESTSHORT.NS", capital=400000, daily_risk_pct=2.0, risk_per_trade_pct=2.0,
        stop_pct=2.0, rr=3.0, sma_fast=9, sma_slow=21, interval="5m",
        tz_offset_min=main.IST_OFFSET_MIN, open_min=0, close_min=1439, squareoff_min=1438,
        trade_weekends=True, currency="INR", max_hold_minutes=120.0, ma_type="ema",
        require_real_tradability=False,
    )
    assert result["action_taken"] == "entered_short", result
    assert result["market_regime"] == "range"

    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM signal_state_short WHERE symbol = ?", ("TESTSHORT.NS",)).fetchone()
        assert row is not None
        assert row["status"] == "short"
        assert row["stop_loss"] > row["entry_price"]
        assert row["target"] < row["entry_price"]
        assert row["qty"] > 0


def test_short_signal_core_stop_hit_closes_and_realizes_pnl(monkeypatch):
    _fresh_db()
    df = _ranging_with_a_sharp_spike()
    monkeypatch.setattr(main, "fetch_ohlc", _FakeYFinance(df))
    monkeypatch.setattr(main, "get_fx_to_inr", lambda currency: 1.0)

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, entry_regime, peak_ltp, strategy) "
            "VALUES ('TESTSHORT.NS', ?, 'short', 100.0, 102.0, 102.0, 85.0, 10, ?, 1.0, '5m', 'range', 100.0, 'range_short')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()

    # Price has since risen above the stop (102.0 < the fixture's own
    # spike-bar close of 104.0) - stop_hit must fire and realize a LOSS
    # (price rose after a short).
    result = main._short_signal_core(
        symbol="TESTSHORT.NS", capital=400000, daily_risk_pct=2.0, risk_per_trade_pct=2.0,
        stop_pct=2.0, rr=3.0, sma_fast=9, sma_slow=21, interval="5m",
        tz_offset_min=main.IST_OFFSET_MIN, open_min=0, close_min=1439, squareoff_min=1438,
        trade_weekends=True, currency="INR", max_hold_minutes=120.0, ma_type="ema",
        require_real_tradability=False,
    )
    assert result["action_taken"] == "exited_short_stop_hit", result
    assert result["pnl_inr"] < 0, "price rose above a short's stop - must realize a loss, not a gain"

    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT 1 FROM signal_state_short WHERE symbol = ?", ("TESTSHORT.NS",)).fetchone() is None
        closed = conn.execute("SELECT * FROM short_trades_closed WHERE symbol = ?", ("TESTSHORT.NS",)).fetchone()
        assert closed is not None
        assert closed["exit_reason"] == "stop_hit"


# ---- _execute_staged_leg_exit_short (2026-09-29, explicit user instruction:
# "mirror that buy to sell into a mirror opposite image ... and same for
# remaining conditions" - don't stop at mirroring the entry trigger/stop/
# target formulas, mirror the long side's staged profit-booking ladder too.
# Mirrors test_universal_score_engine.py's own
# test_execute_staged_leg_exit_* tests.) --------------------------------------

def _insert_open_signal_state_short(conn, symbol="TESTSHORT.NS", entry_price=100.0, qty=8, exit_legs=None):
    conn.execute(
        "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, entry_regime, peak_ltp, strategy, exit_legs_json) "
        "VALUES (?, ?, 'short', ?, ?, ?, ?, ?, ?, 1.0, '5m', 'range', ?, 'range_short', ?)",
        (symbol, main.ist_now().strftime("%Y-%m-%d"), entry_price, entry_price + 2, entry_price + 2,
         entry_price - 6, qty, main.time.time(), entry_price, json.dumps(exit_legs) if exit_legs else None),
    )
    conn.commit()


def test_execute_staged_leg_exit_short_books_partial_qty_and_keeps_position_open():
    _fresh_db()
    # r_multiples point DOWN from entry, mirroring _compute_target_cluster_short
    legs = main._split_exit_legs(8, {"1.0R": 98.0, "1.5R": 97.0, "2.0R": 96.0})
    with closing(main.get_db()) as conn:
        _insert_open_signal_state_short(conn, qty=8, exit_legs=legs)
        booking = main._execute_staged_leg_exit_short(conn, "TESTSHORT.NS", "T1", 2, 97.5, 100.0, 1.0)
        assert booking["booked"] is True
        assert booking["remaining_qty"] == 6
        assert booking["pnl_inr"] > 0, "price fell after a short - a covered leg must realize a gain"

        row = conn.execute("SELECT * FROM signal_state_short WHERE symbol = 'TESTSHORT.NS'").fetchone()
        assert row is not None, "position must stay open - only a partial qty covered"
        assert row["qty"] == 6
        stored_legs = json.loads(row["exit_legs_json"])
        t1 = next(l for l in stored_legs if l["leg"] == "T1")
        assert t1["status"] == "filled"

        closed_rows = conn.execute(
            "SELECT * FROM short_trades_closed WHERE symbol = 'TESTSHORT.NS'"
        ).fetchall()
        assert len(closed_rows) == 1
        assert closed_rows[0]["exit_reason"] == "staged_leg_T1"
        assert closed_rows[0]["qty"] == 2


def test_execute_staged_leg_exit_short_closes_position_when_it_drains_the_remaining_qty():
    _fresh_db()
    legs = main._split_exit_legs(1, {})  # single trail leg, qty=1
    with closing(main.get_db()) as conn:
        _insert_open_signal_state_short(conn, qty=1, exit_legs=legs)
        booking = main._execute_staged_leg_exit_short(conn, "TESTSHORT.NS", "trail", 1, 95.0, 100.0, 1.0)
        assert booking["booked"] is True
        assert booking["remaining_qty"] == 0
        row = conn.execute("SELECT * FROM signal_state_short WHERE symbol = 'TESTSHORT.NS'").fetchone()
        assert row is None  # fully closed


def test_execute_staged_leg_exit_short_returns_not_booked_when_no_open_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        booking = main._execute_staged_leg_exit_short(conn, "NOPOS.NS", "T1", 1, 100.0, 100.0, 1.0)
        assert booking == {"booked": False}


def test_short_signal_core_books_a_staged_leg_and_keeps_the_rest_open(monkeypatch):
    _fresh_db()
    df = _ranging_with_a_sharp_spike()
    monkeypatch.setattr(main, "fetch_ohlc", _FakeYFinance(df))
    monkeypatch.setattr(main, "get_fx_to_inr", lambda currency: 1.0)

    with closing(main.get_db()) as conn:
        # qty=8 -> 3 fixed legs (T1/T2/T3) + trail, per _split_exit_legs.
        # Entry 106.0, T1 at 104.5 (a shallow 1.5-point move) sits just
        # ABOVE the fixture's own spike-bar close (104.0 - the fixed
        # today_df/last_close this tick sees) so exit_price <= T1 fires and
        # fills T1 only; T2/T3 sit further below and are untouched.
        legs = main._split_exit_legs(8, {"1.0R": 104.5, "1.5R": 102.0, "2.0R": 100.0})
        conn.execute(
            "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, entry_regime, peak_ltp, strategy, exit_legs_json) "
            "VALUES ('TESTSHORT.NS', ?, 'short', 106.0, 110.0, 110.0, 100.0, 8, ?, 1.0, '5m', 'range', 106.0, 'range_short', ?)",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time(), json.dumps(legs)),
        )
        conn.commit()

    result = main._short_signal_core(
        symbol="TESTSHORT.NS", capital=400000, daily_risk_pct=2.0, risk_per_trade_pct=2.0,
        stop_pct=2.0, rr=3.0, sma_fast=9, sma_slow=21, interval="5m",
        tz_offset_min=main.IST_OFFSET_MIN, open_min=0, close_min=1439, squareoff_min=1438,
        trade_weekends=True, currency="INR", max_hold_minutes=120.0, ma_type="ema",
        require_real_tradability=False,
    )
    assert result["action_taken"] == "partial_booked_T1", result
    assert result["staged_exit"]["booked"] is True

    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM signal_state_short WHERE symbol = ?", ("TESTSHORT.NS",)).fetchone()
        assert row is not None, "only T1 filled - position must stay open with the remaining qty"
        assert row["qty"] == 6
        closed = conn.execute(
            "SELECT * FROM short_trades_closed WHERE symbol = ? AND exit_reason = 'staged_leg_T1'",
            ("TESTSHORT.NS",),
        ).fetchone()
        assert closed is not None
        assert closed["qty"] == 2
