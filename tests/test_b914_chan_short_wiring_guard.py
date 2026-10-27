"""B-914 guard: every wired chan_kalman SHORT cell stays tied to its real-main.py replay evidence and always
carries a stop. Locks in the B-914 steps already shipped (port, real-main.py replay 38390561217 at 0.8%,
MIS-cost sensitivity 38394789725 at 0.3%, wiring per INTRADAY_FLATTEN_WIRING_SPEC) so a later edit cannot
wire a cell without evidence, drop the stop, or point the replay harness at a reimplementation."""
import inspect
import json
import os
import sqlite3
from contextlib import closing

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "backtest_data")


def _rows(run_id):
    d = json.load(open(os.path.join(DATA, f"chan_kalman_main_replay_run_{run_id}.json")))
    return d, {r["tag"]: r["metrics"] for r in d["rows"]}


def test_every_wired_cell_has_main_replay_at_conservative_cost_clearing_floor():
    d, rows = _rows(38390561217)
    assert d["cost_round_trip_pct"] == 0.8  # the registered conservative cost, not the 0.3% sensitivity
    for t in main.CHAN_SHORT_CELLS:
        assert t in rows, f"{t} wired without a stored main.py replay row"
        m = rows[t]
        assert m["pfnet"] >= sr.PFNET_LIVE_FLOOR, (t, m["pfnet"])
        assert m["n"] >= 30, (t, m["n"])
        assert "cst0d3" not in t  # 0.3%-cost rows are never the wired tag


def test_cost_sensitivity_run_on_file_and_every_wired_cell_stronger_at_lower_cost():
    d03, rows03 = _rows(38394789725)
    _, rows08 = _rows(38390561217)
    assert d03["cost_round_trip_pct"] == 0.3
    by_base = {t.replace("_cst0d3", ""): m for t, m in rows03.items()}
    for t in main.CHAN_SHORT_CELLS:
        if t in by_base:
            assert by_base[t]["pfnet"] >= rows08[t]["pfnet"]


def test_replay_harness_calls_real_main_functions():
    src = open(os.path.join(ROOT, "scripts", "intraday_flatten_rerun.py")).read()
    assert "import main as app" in src
    assert "app.chan_kalman_band_short_entry_signal" in src
    assert "app.chan_kalman_band_short_exit_reason" in src


def test_gate_and_real_path_invariants():
    for t in main.CHAN_SHORT_CELLS:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t not in main.REPLAY_OWED_TAGS
    src = inspect.getsource(main._maybe_place_real_short_entry)
    assert "_is_strategy_viable_for_real_money" in src
    assert "entry_sl_failed_unwind" in src
    assert "CHAN_SHORT_ENTRY_CUTOFF_MIN" in src
    assert main.CHAN_SHORT_ENTRY_CUTOFF_MIN < main.CHAN_SHORT_FLATTEN_START_MIN < main.CHAN_SHORT_FLATTEN_END_MIN
    assert main.CHAN_SHORT_FLATTEN_END_MIN <= 15 * 60 + 15  # flat before the exchange's 15:15 cancel


def test_paper_entry_always_sets_stop_above_entry(monkeypatch):
    n = 200
    idx = pd.date_range("2026-10-20 03:45", periods=n, freq="5min", tz="UTC")
    close = np.linspace(100, 110, n)
    df = pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close,
                       "Volume": np.full(n, 1e6)}, index=idx)
    ts = pd.Series(idx)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE signal_state (symbol TEXT, status TEXT)")
    conn.execute("CREATE TABLE signal_state_short (symbol TEXT PRIMARY KEY, day TEXT, status TEXT, entry_price REAL, "
                 "stop_loss REAL, initial_stop_loss REAL, target REAL, qty REAL, entry_ts REAL, fx_to_inr REAL, "
                 "interval TEXT, entry_regime TEXT, peak_ltp REAL, strategy TEXT, exit_legs_json TEXT)")
    monkeypatch.setattr(main, "_chan_short_frame", lambda d, t: d)
    monkeypatch.setattr(main, "_chan_live_masks", lambda i, iv: None)
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: None)
    monkeypatch.setattr(main, "chan_kalman_band_short_entry_signal",
                        lambda dfc, iv, z, ve, atr_mult, ks, masks: {"atr": 1.2, "atr_mult": atr_mult})
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda t, *a, **k: True)
    monkeypatch.setattr(main, "_record_strategy_scan", lambda t: None)
    monkeypatch.setattr(main, "_liquidity_gate", lambda d: (True, []))
    monkeypatch.setattr(main, "_likely_lower_circuit_locked", lambda d, s: False)
    monkeypatch.setattr(main, "deployed_notional", lambda c: 0.0)
    res = main._chan_short_try_entry(conn, "X.NS", df, ts, df, 110.0, "2026-10-20", "5m", 400000, 2.0, 1.0, "INR", {})
    assert res and res["action_taken"] == "entered_short"
    row = conn.execute("SELECT * FROM signal_state_short WHERE symbol='X.NS'").fetchone()
    assert row["strategy"] == main.CHAN_SHORT_TAG  # cascade picks the already-live cell first
    assert row["stop_loss"] > row["entry_price"] and row["stop_loss"] == row["initial_stop_loss"]
    assert abs(row["stop_loss"] - (110.0 + 4.0 * 1.2)) < 1e-9
    assert row["qty"] > 0
    conn.close()
