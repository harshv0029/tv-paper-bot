"""B-1472: pooled (in-sample + symbol holdout) PFnet registered as NEW "_pool" variant tags; old rows untouched."""
import strategy_registry_sweeps as srs


def test_pooled_metrics_exact_pool():
    # side A: 10 trades, PF 2, avg +1% -> net 10, L 10, W 20; side B: 10 trades, PF 0.5, avg -1% -> net -10, L 20, W 10
    a = {"pfnet": 2.0, "n": 10, "avg_net_pct": 1.0, "win_pct": 60, "avg_held_bars": 10, "bar_hours": 6.25}
    b = {"pfnet": 0.5, "n": 10, "avg_net_pct": -1.0, "win_pct": 40, "avg_held_bars": 20}
    p = srs._pooled_metrics(a, b)
    assert p["pfnet"] == 1.0 and p["n"] == 20 and p["win_pct"] == 50.0 and p["avg_net_pct"] == 0.0
    assert p["avg_held_hrs"] == 15 * 6.25


def test_pooled_metrics_refuses_undecomposable_side():
    good = {"pfnet": 1.5, "n": 10, "avg_net_pct": 1.0}
    assert srs._pooled_metrics(good, {"pfnet": 1.0, "n": 5, "avg_net_pct": 0.0}) is None   # PF ~ 1
    assert srs._pooled_metrics(good, {"pfnet": 1.4, "n": 5, "avg_net_pct": -0.2}) is None  # sign mismatch
    assert srs._pooled_metrics(good, None) is None


def test_pool_tags_registered_and_originals_kept():
    by = {d.name: d for d in srs.build()}
    pool = by["gap__runaway_pool__long__1d__atr6_h20__v1"]
    assert 1.1 < pool.metrics.pfnet < 1.25 and pool.metrics.n_trades == 1074 + 2400
    orig = by["gap__runaway__long__1d__atr6_h20__v1"]          # holdout-gated row untouched
    assert orig.metrics.pfnet <= 1.02
    combos = [n for n in by if n.startswith("combo__") and "_pool__" in n]
    assert combos and all(by[n].metrics is not None for n in combos)


def test_dropped_live_tag_keeps_exit_rule():
    import json, os, main
    d = json.load(open(os.path.join(os.path.dirname(main.__file__), "docs", "pattern_live_cells.json")))
    entry = {r[0] for r in d["cells"]}
    assert d["exit_only"] and not (entry & {r[0] for r in d["exit_only"]})
    for r in d["exit_only"]:
        assert r[0] in main._PATTERN_LIVE_TAGS and main._PATTERN_LIVE_TAGS[r[0]][2] == int(r[2])
    assert {c[0] for c in main._PATTERN_LIVE_CELLS} == entry   # exit-only rows never enter


def test_exit_only_union_with_previous():
    import importlib.util, os
    spec = importlib.util.spec_from_file_location("g", os.path.join(os.path.dirname(srs.__file__), "scripts", "gen_pattern_live_cells.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    prev = {"cells": [["a", "r", 20, 6.0, 1.2], ["b", "r", 20, 6.0, 1.1]], "exit_only": [["z", "q", 10, 6.0, 1.0]]}
    assert [r[0] for r in g.exit_only([["a", "r", 20, 6.0, 1.3]], prev)] == ["b", "z"]
