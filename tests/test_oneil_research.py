import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import oneil_research as orx  # noqa: E402

GRAMMAR = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*__[a-z0-9_]+?__(long|short)__(1d|1w)__[a-z0-9_]+__v1$")


def _series(n=400, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    v = rng.uniform(1e5, 2e5, n)
    return o, h, l, c, v


def test_tag_grammar_all_cells():
    for tf in ("1d", "1w"):
        for d in ("long", "short"):
            for mode, val in orx.EXITS:
                for ch in (0.05, None):
                    t = orx.tag_for("oneil_pivot", "breakout", d, tf, ch, "80", mode, val, 40)
                    assert GRAMMAR.match(t), t
    assert "atr2d5" not in orx.tag_for("oneil_pivot", "breakout", "long", "1d", 0.05, "none", "atr", 3.0, 40)
    assert "atr2d5" in orx.tag_for("oneil_pivot", "breakout", "long", "1d", 0.05, "none", "atr", 2.5, 40)


def test_rs_rank_percentile():
    idx = pd.RangeIndex(30)
    closes = pd.DataFrame({"A": np.linspace(100, 200, 30), "B": np.linspace(100, 110, 30), "C": np.linspace(100, 60, 30)})
    rs = orx.rs_rank_matrix(closes, 10)
    last = rs.iloc[-1]
    assert last["A"] > last["B"] > last["C"]
    assert 1 <= last.min() and last.max() <= 99


def test_pivot_breakout_signal_and_no_lookahead():
    o, h, l, c, v = _series()
    # force a clean breakout at t=300: flat, then a jump close on huge volume
    c[:] = 100.0
    o[:] = 100.0
    h[:] = 101.0
    l[:] = 99.0
    c[300] = 103.0
    h[300] = 103.5
    v[300] = 1e7
    o[301] = 103.2
    c[200:300] = np.linspace(80, 100, 100)  # above 200DMA not guaranteed; relax by rising trend
    rs = np.full(len(c), 90.0)
    sigs = orx.entry_signals(o, h, l, c, v, rs, orx.CFG["1d"])
    key = ("oneil_pivot", "breakout", "long", 0.05, "none")
    assert key in sigs
    # no signal can appear before enough history for the 200DMA
    assert not sigs[key][:200].any()
    # truncating future data must not change earlier signals (no look-ahead other than next-open chase test)
    sigs2 = orx.entry_signals(o[:290], h[:290], l[:290], c[:290], v[:290], rs[:290], orx.CFG["1d"])
    assert (sigs2[key][:289] == sigs[key][:289]).all()


def test_short_mirror_keys_exist():
    o, h, l, c, v = _series()
    sigs = orx.entry_signals(o, h, l, c, v, np.full(len(c), 50.0), orx.CFG["1d"])
    fams = {(k[0], k[2]) for k in sigs}
    for fam in ("oneil_pivot", "oneil_flatbase", "oneil_newhigh", "oneil_rsscreen"):
        assert (fam, "long") in fams and (fam, "short") in fams


def _flat_then(price_path):
    n = len(price_path)
    c = np.array(price_path, float)
    o = c.copy()
    h = c * 1.001
    l = c * 0.999
    return o, h, l, c


def test_stop_always_hit_on_crash_long_and_short():
    # long: price collapses after entry -> stop exit, loss bounded near the stop (gap uses open)
    path = [100] * 30 + [100, 100, 90, 80, 70] + [70] * 30
    o, h, l, c = _flat_then(path)
    atr = np.full(len(c), 2.0)
    sig = np.zeros(len(c), bool)
    sig[29] = True
    rows = orx.simulate(sig, o, h, l, c, atr, 20, "atr", 3.0, 1, 0.008, 3)
    assert rows and rows[0][3] == "stop" and rows[0][0] < 0
    # short: price spikes
    path = [100] * 30 + [100, 100, 110, 120, 130] + [130] * 30
    o, h, l, c = _flat_then(path)
    rows = orx.simulate(sig, o, h, l, c, atr, 20, "pct", 7.0, -1, 0.008, 3)
    assert rows and rows[0][3] == "stop" and rows[0][0] < 0


def test_cost_applied_and_target_exit():
    path = [100] * 30 + [100, 110, 125, 125] + [125] * 30
    o, h, l, c = _flat_then(path)
    atr = np.full(len(c), 2.0)
    sig = np.zeros(len(c), bool)
    sig[29] = True
    rows = orx.simulate(sig, o, h, l, c, atr, 20, "tgt", 20.0, 1, 0.008, 3)
    net, gross, held, reason = rows[0]
    assert reason == "target" and abs((gross - net) - 0.008) < 1e-12 and gross >= 0.20 - 1e-9


def test_trailing_stop_ratchets_up_only():
    # rise with a pullback low, then break the pullback low -> trail_stop above the initial stop
    path = [100] * 30 + [100, 105, 110, 115, 120, 116, 113, 117, 122, 126, 128, 129, 112, 105, 100] + [100] * 20
    n = len(path)
    c = np.array(path, float)
    o = c.copy()
    h = c * 1.002
    l = c * 0.998
    atr = np.full(n, 3.0)
    sig = np.zeros(n, bool)
    sig[29] = True
    rows = orx.simulate(sig, o, h, l, c, atr, 25, "trl", 3.0, 1, 0.008, 2)
    assert rows[0][3] == "trail_stop" and rows[0][1] > 0.0


def test_avg_down_control_marks_reason():
    path = [100] * 30 + [100, 100, 96, 100, 104] + [104] * 30
    o, h, l, c = _flat_then(path)
    l[32] = 93.0
    atr = np.full(len(c), 4.0)
    sig = np.zeros(len(c), bool)
    sig[29] = True
    rows = orx.simulate(sig, o, h, l, c, atr, 20, "avg", 3.0, 1, 0.008, 3)
    assert "avgdown" in rows[0][3]


def test_finalize_and_merge_additive():
    a, b = {}, {}
    orx.acc_add(a, "t", [(0.10, 0.108, 5, "timeout")] * 20 + [(-0.05, -0.042, 3, "stop")] * 20)
    orx.acc_add(b, "t", [(0.10, 0.108, 5, "timeout")] * 20 + [(-0.05, -0.042, 3, "stop")] * 20)
    m = orx.merge_cells([a, b])
    r = orx.finalize(m)["t"]
    assert r["n"] == 80 and r["win_pct"] == 50.0 and abs(r["pfnet"] - 2.0) < 1e-9
    assert r["avg_held_bars"] == 4.0 and set(r["exit_reasons"]) == {"timeout", "stop"}


def test_workflow_matrix_within_limits():
    wf = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows", "oneil-research.yml")).read()
    assert "workflow_dispatch" in wf and "_load_nse_universe_from_file" in wf
    shards = len(re.findall(r"shard: \[([^\]]*)\]", wf)[0].split(","))
    tfs = len(re.findall(r'tf: \[([^\]]*)\]', wf)[0].split(","))
    assert shards <= 4 and shards * tfs + tfs <= 8
