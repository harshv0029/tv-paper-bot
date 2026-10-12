"""B-881: scripts/swing_short_main_replay.py drives the REAL main.py swingminrr / short-swing functions."""
import os
import sys

import numpy as np
import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import swing_short_main_replay as R  # noqa: E402

COST = main.ROUND_TRIP_COST_PCT / 100.0


def _frame(close, high=None, low=None, open_=None):
    close = np.asarray(close, float)
    o = close.copy() if open_ is None else np.asarray(open_, float)
    h = np.maximum(close, o) + 0.3 if high is None else np.asarray(high, float)
    l = np.minimum(close, o) - 0.3 if low is None else np.asarray(low, float)
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": close, "Volume": 1000.0})
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _short_case():
    c = np.full(130, 100.0)
    c[90] = 98.0                      # breakdown below the prior 20-bar low (99.7), with the 60-bar room spike below
    c[91:] = 98.0 + np.arange(1, 40) * 0.5   # then a steady climb that must hit the ATR stop
    low = np.minimum(c, c) - 0.3
    low[40] = 60.0
    return _frame(c, low=low)


def test_tag_specs_cover_both_registries():
    specs = R.tag_specs(main)
    assert set(main.SWINGMINRR_TAGS) <= set(specs) and set(main.SHORT_SWING_TAGS) <= set(specs)
    assert len(main.SWINGMINRR_TAGS) == 4 and len(main.SHORT_SWING_TAGS) == 6
    assert {s["dir"] for t, s in specs.items() if t in main.SHORT_SWING_TAGS} == {"short"}


def test_short_replay_calls_real_functions_and_stops_out(monkeypatch):
    specs = R.tag_specs(main)
    tag = main.SHORT_SWING_TAGS[-1]   # atr3_rr3
    calls = {"entry": 0, "exit": 0}
    real_e, real_x = main.brk20_min_rr_entry_signal, main._short_swing_exit_reason
    monkeypatch.setattr(main, "brk20_min_rr_entry_signal", lambda *a, **k: (calls.__setitem__("entry", calls["entry"] + 1), real_e(*a, **k))[1])
    monkeypatch.setattr(main, "_short_swing_exit_reason", lambda *a, **k: (calls.__setitem__("exit", calls["exit"] + 1), real_x(*a, **k))[1])
    tr = R.replay_symbol(main, _short_case(), tag, specs[tag], COST)
    assert calls["entry"] > 0 and calls["exit"] > 0
    assert len(tr) >= 1
    t = tr[0]
    assert t["reason"].startswith("short_swing_") and t["reason"] in ("short_swing_rule_exit", "short_swing_stop_loss", "short_swing_protected_stop")
    assert t["gross"] < 0 and abs(t["net"] - (t["gross"] - COST)) < 1e-12


def test_long_replay_vcp_gate_and_adapter(monkeypatch):
    """VCP detector forced to fire once (it is the shared upstream gate); swingminrr entry/exit are the real fns."""
    c = np.full(130, 100.0)
    c[100:] = 100.0 - np.arange(0, 30) * 0.8   # decline after entry -> ATR stop
    h = c + 0.3
    h[40] = 130.0                              # room above the signal price for rr gates
    df = _frame(c, high=h)
    sig_idx = {99}
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", lambda d, rs_percentile=None: {"x": 1} if len(d) - 1 in sig_idx else None)
    specs = R.tag_specs(main)
    tr = R.replay_symbol(main, df, main.SWINGMINRR_BASE_TAG, specs[main.SWINGMINRR_BASE_TAG], COST)
    assert len(tr) == 1 and tr[0]["reason"] == "swingminrr_stop_loss" and tr[0]["gross"] < 0
    # gate4 needs room >= 4R: spike of 30 above vs risk ~1.5 x ATR(~0.6) -> passes; no-signal bars never trade
    sig_idx.clear()
    assert R.replay_symbol(main, df, main.SWINGMINRR_BASE_TAG, specs[main.SWINGMINRR_BASE_TAG], COST) == []


def test_fill_next_open_differs_and_merge_roundtrip(tmp_path):
    specs = R.tag_specs(main)
    tag = main.SHORT_SWING_TAGS[-1]
    a = R.replay_symbol(main, _short_case(), tag, specs[tag], COST, "signal_close")
    b = R.replay_symbol(main, _short_case(), tag, specs[tag], COST, "next_open")
    assert a and b
    agg = R.B.agg_new()
    R.B.agg_add(agg, a)
    import json
    (tmp_path / "swingshort_short_s0.json").write_text(json.dumps({
        "shard": 0, "nshards": 1, "n_symbols": 1, "fill_model": "signal_close", "cost_round_trip_pct": main.ROUND_TRIP_COST_PCT,
        "period": "5y", "interval": "1d", "synthetic": True, "note": "t", "cells": {tag: {"spec": specs[tag], "raw": agg}}}))
    out = R.merge(str(tmp_path))
    row = out["rows"][0]
    assert row["tag"] == tag and row["metrics"]["n"] == len(a) and "avg_held_hours" in row["metrics"]


def test_plan_matrix():
    m = R.plan({"REPLAY_GROUPS": "long,short", "NSHARDS": "3"})
    assert len(m["include"]) == 6
