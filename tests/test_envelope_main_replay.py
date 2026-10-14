"""B-1160: envelope main.py replay script: prefilter exactness, short sign, merge schema, workflow validity."""
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import yaml

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import main as app  # noqa: E402

spec = importlib.util.spec_from_file_location("envelope_main_replay", R / "scripts" / "envelope_main_replay.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def _df(seed, n=400):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.012, n)
    r[rng.integers(30, n - 40, 6)] -= 0.09   # sharp drops -> long fades
    r[rng.integers(30, n - 40, 6)] += 0.09   # sharp spikes -> short fades
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.003, np.minimum(o, c) * 0.997
    return pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=1000.0),
                        index=pd.date_range("2025-01-01", periods=n, freq="h"))


def _brute(m, df, tags, cost):
    df = df.reset_index(drop=True)
    out, free = {t: [] for t in tags}, {t: 0 for t in tags}
    for k in range(ev.MIN_BARS - 1, len(df) - 1):
        sub = df.iloc[:k + 1]
        for t in tags:
            if k < free[t]:
                continue
            sig = m.envelope_fade_entry_signal(sub, t)
            if sig:
                tr = ev.envelope_trade(m, df, k, sig, t, cost)
                out[t].append(tr)
                free[t] = tr["exit_i"] + 1
    return out


def test_prefilter_is_exact_and_both_directions_trade():
    tags = list(app.ENVELOPE_1H_CELLS)
    seen_dirs = set()
    for seed in (1, 2):
        df = _df(seed)
        a = ev.replay_symbol(app, df, tags, 0.008)
        b = _brute(app, df, tags, 0.008)
        for t in tags:
            assert [(x["entry_i"], x["exit_i"], x["reason"]) for x in a[t]] == [(x["entry_i"], x["exit_i"], x["reason"]) for x in b[t]]
            if a[t]:
                seen_dirs.add(app.ENVELOPE_1H_CELLS[t][0])
    assert seen_dirs == {"long", "short"}


def test_short_pnl_sign_and_stop_present():
    df = _df(2)
    for t, (d, _k, _h) in app.ENVELOPE_1H_CELLS.items():
        for tr in ev.replay_symbol(app, df, [t], 0.008)[t]:
            assert abs(tr["net"] - (tr["gross"] - 0.008)) < 1e-12
            assert tr["reason"] in ("envelope_stop_loss", "envelope_max_hold_timeout", "data_end_forced_close")
    ep, xp = 100.0, 90.0
    assert ev._trade(ep, xp, 3, "x", 0.0, 1, 4, -1.0)["gross"] > 0 > ev._trade(ep, xp, 3, "x", 0.0, 1, 4, 1.0)["gross"]


def test_merge_schema(tmp_path):
    import brk20_replay as br
    agg = br.agg_new()
    br.agg_add(agg, [{"gross": 0.05, "net": 0.042, "held": 4, "reason": "envelope_max_hold_timeout"},
                     {"gross": -0.02, "net": -0.028, "held": 2, "reason": "envelope_stop_loss"}])
    shard = {"family": "envelope", "interval": "1h", "period": "730d", "cost_round_trip_pct": 0.8, "synthetic": True,
             "direction": "both", "note": "n", "n_symbols": 2, "bars_dropped_glitch": 3,
             "cells": {"envelope__0d05_fade__long__1h__atr6_h30__v1": {"raw": agg}}}
    (tmp_path / "envelope_s0.json").write_text(json.dumps(shard))
    out = ev.merge(str(tmp_path), str(tmp_path / "all.json"))
    m = out["rows"][0]["metrics"]
    assert out["bars_dropped_glitch"] == 3 and m["n"] == 2 and m["pfgross"] and m["exit_reasons"]


def test_workflow_valid():
    wf = yaml.safe_load((R / ".github/workflows/envelope-main-replay.yml").read_text())
    assert "replay" in wf["jobs"] and "merge" in wf["jobs"]
    assert "envelope_main_replay.py" in (R / ".github/workflows/envelope-main-replay.yml").read_text()
