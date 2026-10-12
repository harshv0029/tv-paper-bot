import ast
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_stop_offset_research as so  # noqa: E402
import elder_pyramid_research as py  # noqa: E402
import elder_invalidation_research as iv  # noqa: E402
import elder_lab_driver as drv  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402

MODS = (so, py, iv, drv)


@pytest.mark.parametrize("mod", MODS)
def test_parses(mod):
    ast.parse(open(mod.__file__).read())


def test_round_levels():
    assert so.nearest_round(89.75) == 90
    assert so.nearest_round(1523.0) == 1500
    import numpy as np
    st = so.make_stop((None, None, np.array([1.0])), 0, 90.3, 1, 1.0, "snap", 0)
    assert st is None or st < 90.3


def test_stop_offset_runs_both_directions_and_bounded_loss():
    aggs = {}
    for fam in so.FAMILIES:
        for seed in (1, 2, 3):
            so.run_symbol(synth(900, seed), fam, "1d", aggs)
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    df = synth(900, 2)
    for d in ("long", "short"):
        for t in so.sim(df, so.BASES["dip"](df), d, 2.0, "atr"):
            assert t["ret"] > -0.45          # stop on every trade


def test_structural_stop_never_wider_than_atr_clamp():
    import numpy as np
    h = np.array([100.0, 101, 102])
    l = np.array([90.0, 95, 99])
    st = so.make_stop((h, l, np.ones(3)), 2, 101.0, 1, 2.0, "struct", 0.25)
    assert st == 101.0 - 2.0          # swing low 90 is wider than 2 ATR -> raw ATR stop


def test_pyramid_accept_rules():
    u = [{"px": 100.0, "qty": 0.001}]
    assert py.accept_add(u, 1, 100.0, 105.0, 0.001) == (True, "")
    assert py.accept_add(u, 1, 100.0, 99.0, 5.0)[1] == "avgdown"
    assert py.accept_add(u, 1, 95.0, 105.0, 5.0)[1] == "notbe"
    assert py.accept_add(u, 1, 100.0, 105.0, 5000.0)[1] == "riskcap"
    us = [{"px": 100.0, "qty": 0.001}]
    assert py.accept_add(us, -1, 100.0, 95.0, 0.001) == (True, "")
    assert py.accept_add(us, -1, 100.0, 101.0, 5.0)[1] == "avgdown"


def test_pyramid_runs_and_noadd_has_no_adds():
    aggs = {}
    for seed in (1, 2, 3, 4):
        py.run_symbol(synth(900, seed), "pyramid", "1d", aggs)
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    for t, a in aggs.items():
        if "_noadd__" in t:
            assert a["adds"] == 0
    assert any(a["adds"] > 0 for t, a in aggs.items() if "_noadd__" not in t)
    df = synth(900, 2)
    trig = py.triggers(df)
    for d in ("long", "short"):
        for t in py.sim(df, py.BASES["dip"](df), trig, d, 2.0, "bear", 0.5):
            assert t["ret"] > -1.2 and t["adds"] <= py.MAX_ADDS


def test_invalidation_runs_and_variants_tagged_uniquely():
    aggs = {}
    for seed in (1, 2, 3):
        iv.run_symbol(synth(900, seed), "invalidation", "1d", aggs)
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    assert any("atr6" in t for t in aggs)
    assert len(aggs) == len(set(aggs)) and all(t == t.lower() for t in aggs)
    sig_reasons = set()
    for a in aggs.values():
        sig_reasons |= set(a["reasons"])
    assert "signal_invalidated" in sig_reasons


def test_merge_emits_full_fields(tmp_path):
    aggs = {}
    py.run_symbol(synth(900, 5), "pyramid", "1d", aggs)
    json.dump({"fetched": 1, "universe": 1, "aggs": aggs}, open(tmp_path / "pyramid_0.json", "w"))
    res = drv.merge_dir(str(tmp_path), py.EXTRA)
    r = res["rows"][0]
    for k in ("n", "pfnet", "pf_gross", "win_pct", "avg_hold_bars", "exit_reasons", "adds", "rej_avgdown"):
        assert k in r
    assert res["universe_size"] == 1


@pytest.mark.parametrize("wf", ["elder-stop-offset-research.yml", "elder-pyramid-research.yml",
                                "elder-invalidation-research.yml"])
def test_workflow_matrix_small(wf):
    import re
    txt = open(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", wf)).read()
    assert "workflow_dispatch" in txt and "upload-artifact" in txt
    fam = re.search(r"family: \[(.*?)\]", txt)
    shards = re.search(r"shard: \[(.*?)\]", txt)
    jobs = (len(fam.group(1).split(",")) if fam else 1) * len(shards.group(1).split(","))
    assert jobs <= 40
