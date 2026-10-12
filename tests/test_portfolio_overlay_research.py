import ast
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import portfolio_overlay_research as p  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(p.__file__).read())


def test_collect_and_merge_end_to_end(tmp_path):
    st = {}
    for s in (1, 2, 3):
        p.collect_symbol(synth(900, s), st)
    assert any("|long|" in k for k in st) and any("|short|" in k for k in st)
    json.dump({"fetched": 3, "universe": 3, "streams": st}, open(tmp_path / "collect_0.json", "w"))
    res = p.merge(str(tmp_path), None, synth(1500, 9))
    tags = [r["tag"] for r in res["rows"]]
    assert len(tags) == len(set(tags)) and all(t == t.lower() for t in tags)
    for needle in ("_base__", "_rp1__", "_euphoria_up__", "_lossstreak3__", "_ddladder__", "_gate_dma200__",
                   "_walkfwd_test__", "_month__", "_pricebucket__", "_monitor20__"):
        assert any(needle in t for t in tags), needle
    for k in ("n", "pfnet", "pf_gross", "win_pct", "avg_hold_bars", "universe"):
        assert k in res["rows"][0]


def test_concurrency_cap_and_equity_positive():
    t = [[i, i + 100, 0.05, 0.02, 3, 100.0, 1e6, "x"] for i in range(50)]
    res = p.simulate_portfolio(t, K=10, risk=0.01)
    assert len(res["taken"]) == 10 and res["final_mult"] > 0


def test_independence_and_ci():
    r = list(np.random.default_rng(1).normal(0.001, 0.02, 400))
    assert {"ac1", "ac2", "ac3", "runs_z", "max_losing_run"} <= set(p.independence(r))
    lo, hi = p.boot_ci(r)
    assert lo is not None and lo <= hi


def test_corr_screen_blocks_correlated_concurrent_trade():
    rng = np.random.default_rng(3)
    cal = np.arange(1000, 1300, dtype=np.int64)
    a = rng.normal(0, 0.01, len(cal))
    raw = {"A": [cal.tolist(), a.tolist()], "B": [cal.tolist(), a.tolist()],
           "C": [cal.tolist(), rng.normal(0, 0.01, len(cal)).tolist()]}
    rets, c = p.build_corr_inputs(raw)
    t = [[1250, 1290, 0.05, 0.02, 3, 100.0, 1e6, "x", "A"],
         [1251, 1290, 0.05, 0.02, 3, 100.0, 1e6, "x", "B"],
         [1252, 1290, 0.05, 0.02, 3, 100.0, 1e6, "x", "C"]]
    free = p.simulate_portfolio(t, K=10)
    scr = p.simulate_portfolio(t, K=10, corr={"max": 0.7, "cal": c, "rets": rets})
    assert len(free["taken"]) == 3
    assert [x[8] for x in scr["taken"]] == ["A", "C"]


def test_collect_symbol_records_symbol_and_returns():
    st, rets = {}, {}
    p.collect_symbol(synth(900, 1), st, "ABC", rets)
    assert "ABC" in rets and len(rets["ABC"][0]) == len(rets["ABC"][1])
    assert all(len(t) == 9 and t[8] == "ABC" for v in st.values() for t in v)


def test_collect_symbol_emits_aligned_mark_paths_only_when_asked():
    st0, st1, paths = {}, {}, {}
    p.collect_symbol(synth(900, 1), st0, "ABC")
    p.collect_symbol(synth(900, 1), st1, "ABC", None, paths)
    assert st0 == st1 and paths and set(paths) == set(st1)
    for k, rows in st1.items():
        assert len(paths[k]) == len(rows)
        for row, (secs, closes) in zip(rows, paths[k]):
            assert secs[0] == row[0] and secs[-1] == row[1] and len(secs) == len(closes)
