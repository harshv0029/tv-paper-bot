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
