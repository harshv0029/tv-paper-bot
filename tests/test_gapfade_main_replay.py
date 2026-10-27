"""B-1396d: gapfade main.py replay: per-trade maths, exact prefilter, exit prices, FIFO, RESULTS_JSON schema (offline)."""
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

spec = importlib.util.spec_from_file_location("gapfade_main_replay", R / "scripts" / "gapfade_main_replay.py")
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)
import brk20_replay as br  # noqa: E402

COST = 0.008


def _df(seed, n=500):
    """Random walk with injected down gaps (alternating high/low volume) held for 6 bars, so both tags fire."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0005, 0.012, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.004, np.minimum(o, c) * 0.996
    v = np.full(n, 1e5)
    for idx, g in enumerate(sorted(set(int(x) for x in rng.integers(40, n - 40, 18)))):
        for a in (o, h, l, c):
            a[g:] *= 0.94
        h[g] = min(h[g], l[g - 1] * 0.99)
        o[g] = min(o[g], h[g])
        c[g] = min(c[g], h[g])
        l[g] = min(l[g], o[g], c[g])
        v[g] = 4e5 if idx % 2 else 1e5
        lo = l[g]
        s = slice(g + 1, g + 7)
        l[s] = np.maximum(l[s], lo)
        o[s] = np.maximum(o[s], lo)
        c[s] = np.maximum(c[s], lo)
        h[s] = np.maximum.reduce([h[s], o[s], c[s]])
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": h, "Low": l, "Close": c, "Volume": v})


def _brute(df, tags):
    df = gr._prep(df)
    out, free = {t: [] for t in tags}, {t: 0 for t in tags}
    for k in range(gr.MIN_BARS - 1, len(df) - 1):
        sub = df.iloc[:k + 1]
        for t in tags:
            if k < free[t]:
                continue
            sig = app.gapfade_long_entry_signal(sub, t)
            if sig:
                tr = gr.gapfade_trade(app, df, k, sig, COST)
                out[t].append(tr)
                free[t] = tr["exit_i"] + 1
    return out


def test_trade_metrics_maths():
    t = gr.trade_metrics(100.0, 110.0, 4, "gapfade_rule_exit", COST, 11, 14)
    assert abs(t["gross"] - 0.10) < 1e-12 and abs(t["net"] - 0.092) < 1e-12 and t["held"] == 4
    t = gr.trade_metrics(100.0, 97.0, 1, "gapfade_stop_loss", COST, 11, 11)
    assert abs(t["net"] - (-0.038)) < 1e-12


def test_metrics_aggregation_and_held_days():
    a = br.agg_new()
    br.agg_add(a, [gr.trade_metrics(100, 110, 4, "gapfade_rule_exit", COST, 0, 3),
                   gr.trade_metrics(100, 95, 2, "gapfade_stop_loss", COST, 5, 6),
                   gr.trade_metrics(100, 103, 6, "gapfade_max_hold_timeout", COST, 8, 13)])
    m = gr.metrics(a)
    assert m["n"] == 3 and m["win_pct"] == round(200 / 3, 2)
    assert abs(m["pfnet"] - (0.092 + 0.022) / 0.058) < 1e-9
    assert abs(m["pfgross"] - 0.13 / 0.05) < 1e-9
    assert m["avg_held_days"] == 4.0
    assert set(m["exit_reasons"]) == {"gapfade_rule_exit", "gapfade_stop_loss", "gapfade_max_hold_timeout"}
    assert m["exit_reasons"]["gapfade_stop_loss"]["avg_held_days"] == 2.0


def _key(x):
    return (x["entry_i"], x["exit_i"], x["reason"], round(x["net"], 12))


def test_prefilter_exact_both_tags_trade_and_fifo():
    tags = list(app.GAPFADE_TAGS)
    fired = set()
    for seed in (1, 2, 3):
        df = _df(seed)
        a = gr.replay_symbol(app, df, tags, COST)
        b = _brute(df, tags)
        for t in tags:
            assert [_key(x) for x in a[t]] == [_key(x) for x in b[t]]
            for p, q in zip(a[t], a[t][1:]):
                assert q["entry_i"] > p["exit_i"]  # non-overlapping per symbol per tag
            if a[t]:
                fired.add(t)
    assert fired == set(tags)


def test_stop_exit_is_gap_aware_and_other_exits_at_close():
    df = gr._prep(_df(2))
    res = gr.replay_symbol(app, df, list(app.GAPFADE_TAGS), COST)
    o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    n_checked = 0
    for t, trs in res.items():
        for tr in trs:
            k = tr["entry_i"] - 1
            sig = app.gapfade_long_entry_signal(df.iloc[:k + 1], t)
            assert sig and 0 < sig["stop_loss"] < sig["entry_price"]  # ATR stop always attached
            j = tr["exit_i"]
            xp = min(o[j], sig["stop_loss"]) if tr["reason"] == "gapfade_stop_loss" else c[j]
            assert abs(tr["gross"] - (xp - sig["entry_price"]) / sig["entry_price"]) < 1e-12
            n_checked += 1
    assert n_checked >= 2


def test_merge_results_json_schema(tmp_path, capsys, monkeypatch):
    tags = list(app.GAPFADE_TAGS)
    for s in (0, 1):
        res = gr.replay_symbol(app, _df(s + 1), tags, COST)
        cells = {}
        for t in tags:
            a = br.agg_new()
            br.agg_add(a, res[t])
            cells[t] = {"raw": a}
        (tmp_path / f"gapfade_s{s}.json").write_text(json.dumps(
            {"family": "gapfade", "interval": "1d", "period": "5y", "shard": s, "nshards": 2, "n_symbols": 1,
             "bars_dropped_glitch": 0, "cost_round_trip_pct": 0.8, "synthetic": True, "direction": "long",
             "cells": cells}))
    monkeypatch.delenv("RUN_ID", raising=False)
    out = gr.merge(str(tmp_path), str(tmp_path / "all.json"))
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("RESULTS_JSON: ")]
    assert len(lines) == 1
    j = json.loads(lines[0][len("RESULTS_JSON: "):])
    assert j == json.loads(json.dumps(out))
    assert j["run_id"] is None and j["source"]
    assert {r["tag"] for r in j["rows"]} == set(tags)
    for r in j["rows"]:
        assert set(r["metrics"]) >= {"n", "pfnet", "pfgross", "win_pct", "avg_held_days", "exit_reasons"}
        assert r["shards"] == 2


def test_workflow_and_script_call_live_functions():
    wf = yaml.safe_load((R / ".github" / "workflows" / "gapfade-main-replay.yml").read_text())
    assert wf["jobs"]["replay"]["strategy"]["matrix"]["shard"] == list(range(8))
    src = (R / "scripts" / "gapfade_main_replay.py").read_text()
    assert 'br.load_frames(m, "1d"' in src  # brk20_replay.load_frames -> main._load_nse_universe_from_file()
    assert "m.gapfade_long_entry_signal(" in src and "m._gapfade_exit_adapter(" in src
