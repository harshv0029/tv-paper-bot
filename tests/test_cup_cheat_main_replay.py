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


# ---- B-1190/B-1210 (2026-10-23 IST): short mirror replay (research-side; main.py has no short cup-cheat function) ----

def _dome(seed, tail=60):
    return _recip_df(_cup(seed, tail=tail))


def _brute_short(df, tags, cost):
    df = df.reset_index(drop=True)
    out, free = {t: [] for t in tags}, {t: 0 for t in tags}
    for k in range(cr.MIN_BARS - 1, len(df) - 1):
        sub = df.iloc[:k + 1]
        for t in tags:
            if k < free[t]:
                continue
            sig = sr.cup_cheat_short_entry_signal(sub, t)
            if sig:
                tr = cr.cup_trade(app, df, k, sig, t, cost, "short")
                out[t].append(tr)
                free[t] = tr["exit_i"] + 1
    return out


def test_short_tags_follow_grammar_and_mirror_long_cells():
    assert len(sr.CUP_CHEAT_SHORT_1H_CELLS) == len(app.CUP_CHEAT_1H_CELLS) == 9
    for t, cfg in sr.CUP_CHEAT_SHORT_1H_CELLS.items():
        assert t.startswith("base__cup_cheat_3c__short__1h__atr") and t.endswith("__v1")
        assert app.CUP_CHEAT_1H_CELLS[t.replace("__short__", "__long__")] == cfg


def test_short_prefilter_is_exact_trades_happen_and_no_averaging():
    tags = list(sr.CUP_CHEAT_SHORT_1H_CELLS)
    total = 0
    for seed in range(6):
        df = _dome(seed)
        a = cr.replay_symbol(app, df, tags, 0.008, "short")
        b = _brute_short(df, tags, 0.008)
        for t in tags:
            assert [(x["entry_i"], x["exit_i"], x["reason"]) for x in a[t]] == [(x["entry_i"], x["exit_i"], x["reason"]) for x in b[t]]
            assert all(abs(x["net"] - (x["gross"] - 0.008)) < 1e-12 for x in a[t])
            # no averaging / pyramiding: each new short opens only after the previous one is covered
            for p, q in zip(a[t], a[t][1:]):
                assert q["entry_i"] > p["exit_i"]
            total += len(a[t])
    assert total > 0, "vacuous: no short trades"


def test_short_entry_stop_always_above_entry_every_cell():
    seen = 0
    for seed in range(4):
        dome = _dome(seed)
        for t in range(70, len(dome)):
            sub = dome.iloc[:t + 1]
            for tag, (k, _h) in sr.CUP_CHEAT_SHORT_1H_CELLS.items():
                sig = sr.cup_cheat_short_entry_signal(sub, tag)
                if sig:
                    assert sig["direction"] == "short"
                    assert sig["stop_loss"] > sig["entry_price"]
                    assert abs(sig["stop_loss"] - sig["entry_price"] - k * sig["atr_at_entry"]) < 1e-9
                    seen += 1
    assert seen > 0, "vacuous"
    assert sr.cup_cheat_short_entry_signal(_dome(0), "not_a_tag") is None


def _bars(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"]).assign(Volume=1000.0)


def test_short_exit_stop_above_covers_at_stop_or_gap_open_and_loses():
    entry = [100, 100.5, 99.5, 100]
    # fill bar touches the stop -> cover at the stop
    df = _bars([entry, [100, 105.5, 99, 104]])
    assert sr.cup_cheat_short_exit_reason(df, 0, 105.0, 30) == ("cup_cheat_short_stop_loss", 105.0)
    # later bar gaps above the stop -> cover at the (worse) open, never below the stop
    df = _bars([entry, [100, 101, 99, 100], [107, 108, 106, 107]])
    reason, px = sr.cup_cheat_short_exit_reason(df, 0, 105.0, 30)
    assert reason == "cup_cheat_short_stop_loss" and px == 107.0
    tr = cr._trade(100.0, px, 2, reason, 0.008, 1, 2, "short")
    assert tr["gross"] < 0 and abs(tr["gross"] - (-0.07)) < 1e-12
    # a low below entry never triggers the short's stop
    df = _bars([entry, [100, 101, 80, 85]])
    assert sr.cup_cheat_short_exit_reason(df, 0, 105.0, 30) is None


def test_short_timeout_profit_when_price_falls_below_entry():
    """The mirror has no fixed target (nor does the long rule): the upside is the hold-th close, which profits when BELOW entry."""
    rows = [[100, 100.5, 99.5, 100]] + [[100 - i, 100.5 - i, 99 - i, 99.5 - i] for i in range(1, 7)]
    df = _bars(rows)
    for j in range(1, 6):
        assert sr.cup_cheat_short_exit_reason(df.iloc[:j + 1], 0, 105.0, 6) is None
    reason, px = sr.cup_cheat_short_exit_reason(df, 0, 105.0, 6)
    assert reason == "cup_cheat_short_max_hold_timeout" and px < 100.0
    tr = cr._trade(100.0, px, 6, reason, 0.008, 1, 6, "short")
    assert tr["gross"] > 0 and abs(tr["gross"] - (100.0 - px) / 100.0) < 1e-12


def test_long_replay_default_direction_unchanged():
    assert cr._rule(app, "long")[0] is app.CUP_CHEAT_1H_CELLS
    import pytest
    with pytest.raises(ValueError):
        cr._rule(app, "sideways")


def test_workflow_has_direction_input_and_research_side_note():
    p = R / ".github/workflows/cup-cheat-main-replay.yml"
    txt = p.read_text()
    wf = yaml.safe_load(txt)
    on = wf.get("on", wf.get(True))
    assert on["workflow_dispatch"]["inputs"]["direction"]["options"] == ["long", "short"]
    assert "DIRECTION: ${{ inputs.direction }}" in txt and "RESEARCH-SIDE" in txt
