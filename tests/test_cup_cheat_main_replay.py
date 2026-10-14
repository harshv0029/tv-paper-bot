"""B-1210: cup 3C-cheat main.py replay script (prefilter exactness, merge, workflow) and the inverted-cup short research rule."""
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
sys.path.insert(0, str(R / "tests"))
import main as app  # noqa: E402
import cup_cheat_short_research as sr  # noqa: E402
from test_cup_cheat_main_port import _cup  # noqa: E402

spec = importlib.util.spec_from_file_location("cup_cheat_main_replay", R / "scripts" / "cup_cheat_main_replay.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def _brute(df, tags, cost):
    df = df.reset_index(drop=True)
    out, free = {t: [] for t in tags}, {t: 0 for t in tags}
    for k in range(cr.MIN_BARS - 1, len(df) - 1):
        sub = df.iloc[:k + 1]
        for t in tags:
            if k < free[t]:
                continue
            sig = app.cup_cheat_3c_entry_signal(sub, t)
            if sig:
                tr = cr.cup_trade(app, df, k, sig, t, cost)
                out[t].append(tr)
                free[t] = tr["exit_i"] + 1
    return out


def test_prefilter_is_exact_and_trades_happen():
    tags = list(app.CUP_CHEAT_1H_CELLS)
    total = 0
    for seed in range(6):
        df = _cup(seed, tail=60)
        a = cr.replay_symbol(app, df, tags, 0.008)
        b = _brute(df, tags, 0.008)
        for t in tags:
            assert [(x["entry_i"], x["exit_i"], x["reason"]) for x in a[t]] == [(x["entry_i"], x["exit_i"], x["reason"]) for x in b[t]]
            assert all(abs(x["net"] - (x["gross"] - 0.008)) < 1e-12 for x in a[t])
            total += len(a[t])
    assert total > 0, "vacuous: no cup trades"


def test_merge_schema(tmp_path):
    import brk20_replay as br
    agg = br.agg_new()
    br.agg_add(agg, [{"gross": 0.05, "net": 0.042, "held": 4, "reason": "cup_cheat_max_hold_timeout"},
                     {"gross": -0.02, "net": -0.028, "held": 2, "reason": "cup_cheat_stop_loss"}])
    shard = {"family": "cup_cheat", "interval": "1h", "period": "730d", "cost_round_trip_pct": 0.8, "synthetic": True,
             "direction": "long", "note": "n", "n_symbols": 2, "bars_dropped_glitch": 1,
             "cells": {"base__cup_cheat_3c__long__1h__atr4_h30__v1": {"raw": agg}}}
    (tmp_path / "cupcheat_s0.json").write_text(json.dumps(shard))
    out = cr.merge(str(tmp_path), str(tmp_path / "all.json"))
    assert out["rows"][0]["metrics"]["n"] == 2 and out["bars_dropped_glitch"] == 1


def test_workflow_valid():
    p = R / ".github/workflows/cup-cheat-main-replay.yml"
    wf = yaml.safe_load(p.read_text())
    assert {"replay", "merge"} <= set(wf["jobs"]) and "cup_cheat_main_replay.py" in p.read_text()


def _recip_df(df):
    h, l, c = sr.recip_ohlc(df["High"], df["Low"], df["Close"])
    o = 1.0 / df["Open"].to_numpy(float)
    return pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=df["Volume"].to_numpy(float)), index=df.index)


def test_short_mirror_equals_long_rule_on_reciprocal_series():
    fired = 0
    for seed in range(8):
        cup = _cup(seed)
        dome = _recip_df(cup)  # a dome whose reciprocal is the cup
        for t in range(70, len(cup)):
            s = sr.cup_cheat_short_fires(dome["High"].to_numpy()[:t + 1], dome["Low"].to_numpy()[:t + 1], dome["Close"].to_numpy()[:t + 1])
            assert s == app.cup_cheat_3c_fires(cup.iloc[:t + 1]), (seed, t)
            fired += s
    assert fired > 0, "vacuous"


def test_short_signal_has_stop_above_entry():
    cup = _cup(0)
    dome = _recip_df(cup)
    for t in range(70, len(cup)):
        h, l, c = (dome[x].to_numpy()[:t + 1] for x in ("High", "Low", "Close"))
        sig = sr.cup_cheat_short_signal(h, l, c, 4.0)
        if sig:
            assert sig["stop_loss"] > sig["entry_price"] and sig["direction"] == "short"
            return
    raise AssertionError("no short signal")
