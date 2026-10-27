"""B-1378 (follow-up of B-1252): chan_kalman and chan_gap LONG paths are evaluated even while the aggregate
open-risk gate is closed. A fired cell is counted as a blocked trigger and places nothing (no trade, no
signal_state row); with the gate open the entry path is unchanged."""
import sqlite3

import numpy as np
import pandas as pd
import pytest

import main

CK_TAG = next(iter(main.CHAN_LONG_CELLS))
GAP_TAG = next(iter(main.CHAN_GAP_LONG_CELLS))


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE signal_state_short (symbol TEXT, status TEXT)")
    c.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, qty REAL, price REAL, fx_to_inr REAL, "
              "strategy TEXT, raw_payload TEXT)")
    c.execute("CREATE TABLE signal_state (symbol TEXT PRIMARY KEY, day, status, entry_price, stop_loss, "
              "initial_stop_loss, target, qty, entry_ts, orb_high, orb_low, fx_to_inr, interval, exit_legs_json, "
              "entry_regime, strategy)")
    return c


def _blocked():
    return {k: v for k, v in main._strategy_blocked_triggers.items() if k != "_day"}


@pytest.fixture
def placed(monkeypatch):
    saved = dict(main._strategy_blocked_triggers)
    main._strategy_blocked_triggers.clear()
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "_liquidity_gate", lambda df: (True, ""))
    monkeypatch.setattr(main, "_likely_lower_circuit_locked", lambda df, d: False)
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 0.0)
    calls = []
    monkeypatch.setattr(main, "apply_paper_trade", lambda *a, **k: calls.append(a))
    yield calls
    main._strategy_blocked_triggers.clear()
    main._strategy_blocked_triggers.update(saved)
    main._CHAN_GAP_STATE.update(day=None, ready=False, building=False, selected={})


def _ck_fire(monkeypatch, fires=True):
    idx = pd.date_range("2026-10-14 09:15", periods=5, freq="5min")
    df = pd.DataFrame({"Close": np.full(5, 100.0)}, index=idx)
    monkeypatch.setattr(main, "_chan_short_frame", lambda d, t: df)
    monkeypatch.setattr(main, "_chan_live_masks", lambda i, iv: None)
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: None)
    monkeypatch.setattr(main, "chan_kalman_band_long_entry_signal",
                        (lambda *a, **k: {"atr_mult": k["atr_mult"], "atr": 1.0}) if fires else (lambda *a, **k: None))
    return df


def _ck(conn, df, result, agg_blocked):
    return main._chan_long_try_entry(conn, "X.NS", df, 0, 100.0, "2026-10-14", "5m", 1e5, 1.0, 1.0, "INR", result,
                                     agg_blocked=agg_blocked)


def test_chan_kalman_fired_while_gate_closed_counts_blocked_and_places_nothing(monkeypatch, placed):
    df, conn, result = _ck_fire(monkeypatch), _conn(), {}
    assert _ck(conn, df, result, True) is None  # falls through; the caller still evaluates and gates universal-score
    assert _blocked() == {CK_TAG: 1}
    assert result["blocked_aggregate_open_risk_triggers"] == [CK_TAG]
    assert placed == []
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM signal_state").fetchone()[0] == 0


def test_chan_kalman_not_fired_while_gate_closed_counts_nothing(monkeypatch, placed):
    df = _ck_fire(monkeypatch, fires=False)
    assert _ck(_conn(), df, {}, True) is None
    assert _blocked() == {}


def test_chan_kalman_gate_open_reaches_order_path_unchanged(monkeypatch, placed):
    df, conn = _ck_fire(monkeypatch), _conn()
    out = _ck(conn, df, {}, False)
    assert out["action_taken"] == "entered_long" and len(placed) == 1
    assert _blocked() == {}


def _gap_select():
    main._CHAN_GAP_STATE.update(day="2026-10-14", ready=True, building=False,
                                selected={"X.NS": {"entry_price": 100.0, "atr_at_entry": 1.0, "gap": -0.02,
                                                   "score": -0.02}})


def _gap(conn, sym, result, agg_blocked):
    return main._chan_gap_long_try_entry(conn, sym, None, None, 100.0, "2026-10-14", "5m", 1e5, 1, 1, "INR", result,
                                         mins_now=600, universe=[sym], agg_blocked=agg_blocked)


def test_chan_gap_fired_while_gate_closed_counts_blocked_and_places_nothing(placed):
    _gap_select()
    conn, result = _conn(), {}
    assert _gap(conn, "X.NS", result, True) is None
    assert _blocked() == {GAP_TAG: 1}
    assert result["blocked_aggregate_open_risk_triggers"] == [GAP_TAG]
    assert placed == []
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM signal_state").fetchone()[0] == 0


def test_chan_gap_unselected_symbol_while_gate_closed_counts_nothing(placed):
    _gap_select()
    assert _gap(_conn(), "Y.NS", {}, True) is None
    assert _blocked() == {}


def test_chan_gap_already_entered_today_is_not_counted(placed):
    _gap_select()
    conn = _conn()
    conn.execute("INSERT INTO trades (ts, symbol, action, strategy) VALUES (?, 'X.NS', 'buy', ?)",
                 (main.ist_midnight_epoch(main.ist_now()) + 1, GAP_TAG))
    assert _gap(conn, "X.NS", {}, True) is None
    assert _blocked() == {}


def test_core_passes_gate_flag_to_both_chan_paths():
    import inspect
    src = inspect.getsource(main._auto_signal_core)
    assert "not agg_blocked" not in src
    assert src.count("agg_blocked=agg_blocked") == 2
