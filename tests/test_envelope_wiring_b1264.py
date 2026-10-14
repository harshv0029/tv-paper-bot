"""B-1264: envelope 5% fade LONG 1h (run 38550666361, main.py replay) - 12 own _mr rows, two long cells wired, shorts gated closed."""
import inspect
import json
import os

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

_REG = {d.name: d for d in sr.REGISTRY}
_F = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data", "envelope_main_replay_run_38550666361.json")
_ROWS = json.load(open(_F))["rows"]
LIVE = ("envelope__0d05_fade__long__1h__atr6_h30__v1", "envelope__0d05_fade__long__1h__atr4_h30__v1")


def _mr(t):
    return t.replace("__long__", "_mr__long__", 1).replace("__short__", "_mr__short__", 1)


def test_all_12_rows_registered_with_full_metrics():
    assert len(_ROWS) == 12
    for r in _ROWS:
        d = _REG[_mr(r["tag"])]
        m = d.metrics
        assert m.n_trades == r["n"] and abs(m.pfnet - r["pfnet"]) < 1e-9 and abs(m.pfgross - r["pfgross"]) < 1e-9
        assert abs(m.win_rate_pct - r["win_pct"]) < 1e-9 and abs(m.avg_held_bars - r["avg_held_bars"]) < 1e-9
        assert abs(m.avg_held_hrs - r["avg_held_bars"]) < 1e-9
        want = sr.TradeCategory.SWING if r["direction"] == "long" else sr.TradeCategory.SHORT_SELL
        assert d.categories == (want,)
        assert "38550666361" in m.run_ref and "envelope_main_replay_run_38550666361.json" in d.evidence


def test_gate_opens_for_two_longs_only():
    # floor 1.0 (2026-10-14): every wired long cell with PFnet >= 1.0 opens the gate; cells below 1.0 (e.g. atr4_h18 0.9963) stay closed
    for r in _ROWS:
        ok = main._is_strategy_viable_for_real_money(r["tag"], check_switch=False)
        wired = r["tag"] in main.ENVELOPE_LONG_LIVE_CELLS
        assert ok == (wired and r["pfnet"] >= sr.PFNET_LIVE_FLOOR), r["tag"]
    for t in LIVE:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == _mr(t)
        assert t not in main.REPLAY_OWED_TAGS
    assert set(LIVE) <= set(main.ENVELOPE_LONG_LIVE_CELLS) and len(main.ENVELOPE_LONG_LIVE_CELLS) == 4


def _df(n=80, drop=True):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.2, n))
    if drop:
        c[-1] = c[-21:].mean() * 0.90
    idx = pd.date_range("2026-01-01 09:15", periods=n, freq="h")
    return pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c,
                         "Date": idx.strftime("%Y-%m-%d %H:%M")})


def test_signal_has_stop_and_exit_semantics():
    df = _df()
    for t in LIVE:
        sig = main.envelope_fade_entry_signal(df, t)
        assert sig and 0 < sig["stop_loss"] < sig["entry_price"]
    assert main.envelope_fade_entry_signal(_df(drop=False), LIVE[0]) is None
    pos = {"strategy": LIVE[0], "entry_day": df["Date"].iloc[-1], "initial_stop_loss": 50.0}
    assert main._envelope_long_1h_exit(df, pos) is None
    ext = pd.concat([df, df.iloc[[-1]].assign(Low=1.0, Date="2026-12-01 09:15")], ignore_index=True)
    r = main._envelope_long_1h_exit(ext, pos)
    assert r and r[0] == "envelope_stop_loss"


def test_structural_scan_invoked_and_sl_attached():
    assert "_envelope_long_1h_try_entry" in inspect.getsource(main._run_long_swing_1h_pass)
    assert "ENVELOPE_LONG_LIVE_CELLS" in inspect.getsource(main._run_long_swing_1h_pass)
    src = inspect.getsource(main._envelope_long_1h_try_entry)
    assert "initial_stop_loss" in src and "_maybe_place_real_swing_entry" in src and "envelope_fade_entry_signal" in src
    assert "ENVELOPE_LONG_LIVE_CELLS" in inspect.getsource(main._run_swing_scan_pass)
    assert "entry_sl_failed_unwind" in inspect.getsource(main._maybe_place_real_swing_entry)


def test_try_entry_opens_paper_row_with_stop(monkeypatch):
    import sqlite3
    calls = []
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(main, "_swing_position_size", lambda *a, **k: 5)
    monkeypatch.setattr(main, "apply_paper_trade", lambda *a, **k: None)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close)")
    conn.execute("CREATE TABLE trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload)")
    tag = main._envelope_long_1h_try_entry(conn, "ABC.NS", _df(), 100000, 0.01)
    assert tag == LIVE[0] and len(calls) == 1
    row = conn.execute("SELECT * FROM signal_state_swing").fetchone()
    assert row["strategy"] == tag and row["initial_stop_loss"] < row["entry_price"]
