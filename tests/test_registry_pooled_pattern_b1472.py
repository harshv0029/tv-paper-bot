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


def test_combo_holdout_all_file_fills_gaps_top80_wins(monkeypatch):
    """2026-11-09: combo_validate_results_all.json (every in-sample PFnet > 1 combo) fills tags the top-80 file lacks."""
    files = {"combo_validate_results.json": {"results": {"A": {"pfnet": 1.2}}},
             "combo_validate_results_all.json": {"results": {"A": {"pfnet": 0.9}, "B": {"pfnet": 1.1}}}}
    monkeypatch.setattr(srs, "_load", lambda n: files.get(n, {}))
    got = srs._combo_holdout()
    assert got == {"A": {"pfnet": 1.2}, "B": {"pfnet": 1.1}}


def test_combo_validate_all_pf1_selection_shards_partition():
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("combo_validate_t", os.path.join(root, "scripts", "combo_validate.py"))
    cv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cv)
    cells = {f"combo__a{i}_x_b__long__1d__atr6_h20__v1": {"pfnet": 1.0 + (i % 3) * 0.2, "pfnet_trim1": None, "n": 50}
             for i in range(30)}
    cells["combo__s_x_b__short__1d__atr6_h20__v1"] = {"pfnet": 2.0, "pfnet_trim1": None, "n": 900}
    want = sorted(t for t, m in cells.items() if m["pfnet"] > 1 and "__long__" in t)
    shards = [cv.select_cells(cells, mode="all_pf1", shard=k, shards=4) for k in range(4)]
    assert sorted(sum(shards, [])) == want and len(set(sum(shards, []))) == len(want)
    assert cv.select_cells(cells, mode="top", top=80) == []  # B-18 pick unchanged: n >= 300 required


def test_dirsys13_pooled_variant_rows_registered():
    import strategy_registry as sr
    by = {d.name: d for d in sr.REGISTRY}
    pool = [n for n in by if n.startswith("dirsys13__") and "_pool__" in n]
    assert pool
    n = pool[0]
    base = n.replace("_pool__", "__", 1)
    assert base in by and by[base].metrics.n_trades < by[n].metrics.n_trades  # OOS headline kept, pooled is its own tag
