"""B-1266: every envelope long 1h cell and cup 3C cheat long 1h cell with main.py-replay PFnet >= 1 is WIRED (scanned);
the real-money gate (floor 1.1) is checked only at trigger time."""
import inspect
import json
import os
import sqlite3

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REG = {d.name: d for d in sr.REGISTRY}
_CUP = json.load(open(os.path.join(_ROOT, "docs", "backtest_data", "cup_cheat_main_replay_run_38553281449.json")))["rows"]
_ENV = json.load(open(os.path.join(_ROOT, "docs", "backtest_data", "envelope_main_replay_run_38550666361.json")))["rows"]


def _mr(t):
    return t.replace("__long__", "_mr__long__", 1)


def test_cup_nine_rows_registered():
    assert len(_CUP) == 9
    for r in _CUP:
        d = _REG[_mr(r["tag"])]
        assert d.categories == (sr.TradeCategory.SWING,)
        assert d.metrics.n_trades == r["n"] and abs(d.metrics.pfnet - r["pfnet"]) < 1e-9
        assert abs(d.metrics.win_rate_pct - r["win_pct"]) < 1e-9 and abs(d.metrics.avg_held_bars - r["avg_held_bars"]) < 1e-9


def test_wired_set_is_exactly_pfnet_ge_1():
    env = {r["tag"] for r in _ENV if r["direction"] == "long" and r["pfnet"] >= 1}
    cup = {r["tag"] for r in _CUP if r["pfnet"] >= 1}
    assert set(main.ENVELOPE_LONG_LIVE_CELLS) == env and len(env) == 4
    assert set(main.CUP_CHEAT_LONG_LIVE_CELLS) == cup and len(cup) == 2
    for t in list(env) + list(cup):
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == _mr(t)
        assert t not in main.REPLAY_OWED_TAGS


def test_cup_gate_follows_floor_and_is_scanned():
    # floor 1.0 (2026-10-14): wired cells with PFnet >= 1.0 open the gate; a cell below 1.0 (cup atr4_h30 0.9943) stays closed
    import dataclasses
    import strategy_registry as sr
    reg = {d.name: d for d in sr.REGISTRY}
    for t in main.CUP_CHEAT_LONG_LIVE_CELLS:
        d = reg[main._STRATEGY_TAG_TO_REGISTRY_NAME[t]]
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) == (d.metrics.pfnet >= sr.PFNET_LIVE_FLOOR)
        orig = d.metrics
        object.__setattr__(d, "metrics", dataclasses.replace(orig, pfnet=0.9943))
        try:
            assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False
        finally:
            object.__setattr__(d, "metrics", orig)
    src = inspect.getsource(main._cup_cheat_long_1h_try_entry)
    assert src.index("_record_strategy_scan") < src.index("cup_cheat_3c_entry_signal") < src.index("_is_strategy_wired")
    assert "_record_blocked_trigger" in src and "_maybe_place_real_swing_entry" in src and "initial_stop_loss" in src
    assert "_cup_cheat_long_1h_try_entry" in inspect.getsource(main._run_long_swing_1h_pass)
    assert "CUP_CHEAT_LONG_LIVE_CELLS" in inspect.getsource(main._run_swing_scan_pass)


def test_cup_exit_and_try_entry(monkeypatch):
    tag = main.CUP_CHEAT_LONG_LIVE_CELLS[0]
    n = 90
    idx = pd.date_range("2026-01-01 09:15", periods=n, freq="h")
    c = np.full(n, 100.0)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Date": idx.strftime("%Y-%m-%d %H:%M")})
    pos = {"strategy": tag, "entry_day": df["Date"].iloc[-1], "initial_stop_loss": 90.0}
    assert main._cup_cheat_long_1h_exit(df, pos) is None
    ext = pd.concat([df, df.iloc[[-1]].assign(Low=1.0, Date="2026-12-01 09:15")], ignore_index=True)
    assert main._cup_cheat_long_1h_exit(ext, pos)[0] == "cup_cheat_stop_loss"
    # forced signal: gate open -> paper row with stop; gate closed -> blocked trigger, no row
    monkeypatch.setattr(main, "cup_cheat_3c_entry_signal", lambda d, t: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 4.0, "risk": 10.0, "direction": "long"})
    monkeypatch.setattr(main, "_swing_position_size", lambda *a, **k: 5)
    monkeypatch.setattr(main, "apply_paper_trade", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda *a, **k: calls.append(a))
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close)")
    conn.execute("CREATE TABLE trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload)")
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: False)
    monkeypatch.setattr(main, "_is_strategy_wired", lambda *a, **k: False)
    assert main._cup_cheat_long_1h_try_entry(conn, "ABC.NS", df, 100000, 0.01) is None and not calls
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0] == 0
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "_is_strategy_wired", lambda *a, **k: True)
    assert main._cup_cheat_long_1h_try_entry(conn, "ABC.NS", df, 100000, 0.01) == tag and len(calls) == 1
    assert conn.execute("SELECT initial_stop_loss FROM signal_state_swing").fetchone()[0] == 90.0
