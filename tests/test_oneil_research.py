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


# ---------------- B-489 / B-491 stop 5-10% x target 15-25% + 8-week min-hold sweep (EXIT_SET=stoptgt)
def _one_sig(n, at=29):
    sig = np.zeros(n, bool)
    sig[at] = True
    return sig


def test_stoptgt_exit_set_shape_and_unique_grammar_tags():
    ex = orx.EXIT_SETS["stoptgt"]
    assert len(ex) == 5 + 15 + 15
    assert {v for m, v in ex if m == "pct"} == {5.0, 6.0, 7.0, 8.0, 10.0}
    assert orx.EXIT_SETS["base"] == orx.EXITS_BASE and orx.EXITS == orx.EXITS_BASE  # default env unchanged
    for tf in ("1d", "1w"):
        tags = set()
        for d in ("long", "short"):
            for mode, val in ex:
                mh = orx.MH_BARS[tf] if mode == "tgtmh" else 0
                t = orx.tag_for("oneil_pivot", "breakout", d, tf, 0.05, "none", mode, val, 60, mh)
                assert GRAMMAR.match(t), t
                tags.add(t)
        assert len(tags) == 2 * len(ex)
    # legacy tgt20 tag == the swept 8% stop / 20% target tag (same definition, reproduces run 38193479637)
    a = orx.tag_for("oneil_pivot", "breakout", "long", "1d", 0.05, "none", "tgt", 20.0, 40)
    b = orx.tag_for("oneil_pivot", "breakout", "long", "1d", 0.05, "none", "tgt", (8.0, 20.0, 0), 40)
    assert a == b and "_pct8_" in a and "_tgt20_" in a
    m = orx.tag_for("oneil_pivot", "breakout", "long", "1d", 0.05, "none", "tgtmh", (5.0, 15.0, 1), 60, 40)
    assert "_mh40_" in m and "pct5" in m and "tgt15" in m
    assert "_mh8_" in orx.tag_for("oneil_pivot", "breakout", "short", "1w", None, "none", "tgtmh", (6.0, 25.0, 1), 12, 8)


def test_pct_stop_sweep_levels_long_and_short():
    for sp in orx.STOPS_SWEEP:
        # long: slide 1% per bar -> stop fills at entry*(1-sp%) (within one bar's step)
        path = [100] * 30 + [100 - k for k in range(0, 15)] + [85] * 30
        o, h, l, c = _flat_then(path)
        rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 40, "pct", sp, 1, 0.0, 3)
        assert rows[0][3] == "stop" and abs(rows[0][1] + sp / 100.0) < 0.011, (sp, rows[0])
        # short: buy-to-cover sp% ABOVE entry
        path = [100] * 30 + [100 + k for k in range(0, 15)] + [115] * 30
        o, h, l, c = _flat_then(path)
        rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 40, "pct", sp, -1, 0.0, 3)
        assert rows[0][3] == "stop" and abs(rows[0][1] + sp / 100.0) < 0.011, (sp, rows[0])


def test_target_sweep_and_stop_combo():
    path = [100] * 30 + [100 + 2 * k for k in range(0, 20)] + [140] * 30
    o, h, l, c = _flat_then(path)
    for tp in orx.TARGETS_SWEEP:
        rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 40, "tgt", (5.0, tp, 0), 1, 0.0, 3)
        assert rows[0][3] == "target" and tp / 100.0 - 1e-9 <= rows[0][1] < tp / 100.0 + 0.021, (tp, rows[0])  # gap fills at open
    # short target mirror
    path = [100] * 30 + [100 - 2 * k for k in range(0, 20)] + [60] * 30
    o, h, l, c = _flat_then(path)
    rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 40, "tgt", (7.0, 15.0, 0), -1, 0.0, 3)
    assert rows[0][3] == "target" and 0.15 - 1e-9 <= rows[0][1] < 0.171


def test_minhold_target_inside_8_weeks_holds_to_week8_close():
    # +20% hit on bar e+5 (inside 40 bars) -> NOT sold; held to bar e+39 and exits at that close
    path = [100] * 30 + [100, 105, 110, 115, 118, 121] + [130] * 34 + [126] * 40
    o, h, l, c = _flat_then(path)
    sig = _one_sig(len(c))
    rows = orx.simulate(sig, o, h, l, c, np.full(len(c), 2.0), 60, "tgtmh", (8.0, 20.0, 1), 1, 0.008, 3, mh=40)
    net, gross, held, reason = rows[0]
    assert reason == "mh_exit" and held == 40 and abs(gross - (c[30 + 39] / 100.0 - 1)) < 1e-12
    # same path without the min-hold rule books the target early
    base = orx.simulate(sig, o, h, l, c, np.full(len(c), 2.0), 60, "tgt", (8.0, 20.0, 0), 1, 0.008, 3)
    assert base[0][3] == "target" and base[0][2] == 6


def test_minhold_stop_still_live_and_late_target_taken_normally():
    # target hit early, then collapse through the 8% stop before week 8 -> stop exit
    path = [100] * 30 + [100, 110, 121, 115, 100, 90] + [90] * 70
    o, h, l, c = _flat_then(path)
    rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 60, "tgtmh", (8.0, 20.0, 1), 1, 0.0, 3, mh=40)
    assert rows[0][3] == "stop" and rows[0][1] <= -0.08 + 1e-9  # gap through the stop fills at the open
    # target first reached after week 8 (bar e+45) -> ordinary target exit
    path = [100] * 30 + [100] * 45 + [125] + [125] * 30
    o, h, l, c = _flat_then(path)
    rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 60, "tgtmh", (8.0, 20.0, 1), 1, 0.0, 3, mh=40)
    assert rows[0][3] == "target" and rows[0][2] == 46


def test_minhold_short_mirror_and_weekly_bars():
    path = [100] * 30 + [100, 90, 82, 79] + [75] * 4 + [77] * 20
    o, h, l, c = _flat_then(path)
    rows = orx.simulate(_one_sig(len(c)), o, h, l, c, np.full(len(c), 2.0), 12, "tgtmh", (8.0, 20.0, 1), -1, 0.0, 2, mh=8)
    assert rows[0][3] == "mh_exit" and rows[0][2] == 8 and abs(rows[0][1] - 0.25) < 1e-9


def test_minhold_requires_hold_longer_than_window():
    import pytest
    o, h, l, c = _flat_then([100] * 80)
    with pytest.raises(ValueError):
        orx.simulate(_one_sig(80), o, h, l, c, np.full(80, 2.0), 40, "tgtmh", (8.0, 20.0, 1), 1, 0.0, 3, mh=40)


def test_process_symbol_stoptgt_emits_mh_only_on_long_holds(monkeypatch):
    monkeypatch.setattr(orx, "EXITS", orx.EXITS_STOPTGT)
    monkeypatch.setenv("PATTERNS", "0")
    o, h, l, c, v = _series(600, seed=3)
    v[::25] = 1e7  # volume spikes so breakouts fire
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=pd.RangeIndex(600))
    cells = {}
    orx.process_symbol(df, pd.Series(np.full(600, 85.0)), orx.CFG["1d"], 0.008, "1d", cells)
    mh_tags = [t for t in cells if "_mh40_" in t]
    assert mh_tags and all("_h60_" in t for t in mh_tags)
    assert any("_pct5_" in t and "tgt" not in t for t in cells)
    assert not any("atr" in t for t in cells)
