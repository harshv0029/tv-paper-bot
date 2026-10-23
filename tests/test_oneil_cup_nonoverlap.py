"""B-818 / B-831: O'Neil cup-with-handle strict-FIFO non-overlap + IS/OOS harness (scripts/oneil_cup_nonoverlap.py)."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import macddiv_nonoverlap as no
import oneil_cup_nonoverlap as cn
import oneil_research as orx

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _series(n=500, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    return o, h, l, c, np.full(n, 1e6)


def test_cells_cover_both_directions_avg0_and_avg1_and_exist_in_run_tsv():
    cells = cn.cup_cells()
    assert len(cells) == 16
    tags = {cn.old_tag(*x) for x in cells}
    assert "oneil_cup_handle__breakout__long__1d__atr3_avg1_chase10_h60_rs80__v1" in tags
    assert "oneil_cup_handle__breakout__long__1d__atr3_chase10_h60_rs80__v1" in tags  # no-averaging counterpart
    assert "oneil_cup_handle__breakout__short__1d__atr3_chase5_h60_rsqual1__v1" in tags
    ref = cn.ref_lookup(os.path.join(ROOT, "docs", "backtest_data", "oneil_1d_run_38193479637.tsv"))
    missing = [t for t in tags if t not in ref]
    assert not missing, missing


def test_fifo_kept_trades_never_overlap_and_reproduce_orx_simulate():
    o, h, l, c, _ = _series()
    atr = orx.atr_arr(h, l, c)
    sig = np.zeros(len(c), bool)
    sig[40:420] = True  # signal on every bar -> heavy overlap before the filter
    for mode, val, side in (("atr", 3.0, 1), ("avg", 3.0, 1), ("atr", 3.0, -1)):
        kept, raw = cn.nonovl_trades(sig, o, h, l, c, atr, 20, mode, val, side, 0.008, 3)
        assert raw > len(kept) > 0
        assert not no.has_overlap(kept)
        # signal bar of each kept trade is strictly after the previous kept exit bar
        assert all(b["entry_i"] - 1 > a["exit_i"] for a, b in zip(kept, kept[1:]))
        ref = orx.simulate(sig, o, h, l, c, atr, 20, mode, val, side, 0.008, 3)
        assert [round(r[0], 9) for r in ref] == [round(t["net"], 9) for t in kept]


def test_is_oos_split_partitions_trades_by_entry_date():
    idx = pd.date_range("2021-01-01", periods=100, freq="D")
    trades = [{"entry_i": i, "exit_i": i + 2} for i in (5, 30, 59, 60, 61, 95)]
    ts = no.split_ts(idx, "", 0.6)
    ins, oos = no.segment_trades(trades, idx, ts)
    assert len(ins) + len(oos) == len(trades)
    assert all(idx[t["entry_i"]] < ts for t in ins) and all(idx[t["entry_i"]] >= ts for t in oos)
    ins2, oos2 = no.segment_trades(trades, idx, no.split_ts(idx, "2021-03-01"))
    assert [t["entry_i"] for t in ins2] == [5, 30]  # idx[59] == 2021-03-01 is OOS


def test_run_symbol_cup_emits_new_tags_and_segments_sum_to_pooled():
    o, h, l, c, v = _series(800, seed=3)
    idx = pd.date_range("2020-01-01", periods=800, freq="B")
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)
    df.name = "SYN"
    n = len(c)
    fake = np.zeros(n, bool)
    fake[100:700:7] = True
    import oneil_patterns as op
    orig = op.pattern_signals
    op.pattern_signals = lambda *a, **k: {(cn.CUP_FAMILY, "breakout", d, ch, r): fake
                                          for d in ("long", "short") for ch in cn.CUP_CHASES for r in cn.CUP_RSF}
    try:
        aggs, raw = {}, {}
        cn.run_symbol_cup(df, pd.Series(90.0, index=idx), orx.CFG["1d"], 0.008, aggs, raw)
    finally:
        op.pattern_signals = orig
    pooled = [t for t in aggs if t.endswith("__nonovl__v2")]
    assert len(pooled) == 16
    for t in pooled:
        assert "__v1" not in t
        base = t[: -len("__nonovl__v2")]
        assert aggs[base + "_nonovl_segis__v2"]["n"] + aggs[base + "_nonovl_segoos__v2"]["n"] == aggs[t]["n"]
        assert raw[t] >= aggs[t]["n"]
        assert cn.original_tag(t) == base + "__v1"


def test_merge_writes_tsv_with_run_columns(tmp_path):
    a = cn.onl.new_agg()
    tr = [{"entry_i": i, "exit_i": i, "net": x, "gross": x + 0.008, "hold": 40, "reason": "timeout"}
          for i, x in enumerate([-0.05, 0.2, 0.1])]
    cn.onl.add_trades(a, tr, "AAA", pd.date_range("2024-01-01", periods=5, freq="D"))
    tag = "oneil_cup_handle__breakout__long__1d__atr3_chase10_h60_rs80__nonovl__v2"
    d = tmp_path / "s"
    d.mkdir()
    (d / "oneil_cup_nonovl_1d_0.json").write_text(json.dumps(
        {"fetched": 1, "fetched_symbols": ["AAA"], "raw_signal_trades": {tag: 5}, "aggs": {tag: a}}))
    tsv = tmp_path / "o.tsv"
    assert cn.main(["merge", str(d), "--tsv", str(tsv), "--json", str(tmp_path / "o.json")]) == 0
    lines = tsv.read_text().splitlines()
    ref_cols = open(os.path.join(ROOT, "docs", "backtest_data", "oneil_1d_run_38193479637.tsv")).readline().rstrip("\n")
    assert lines[0] == ref_cols
    row = dict(zip(lines[0].split("\t"), lines[1].split("\t")))
    assert row["tag"] == tag and row["n"] == "3" and row["pfnet"] == str(round(0.3 / 0.05, 3))
    res = json.loads((tmp_path / "o.json").read_text())["results"][tag]
    assert res["raw_signal_trades_before_fifo"] == 5 and res["orig_n"] == 289


def test_workflow_parses_and_calls_script():
    import yaml
    p = os.path.join(ROOT, ".github", "workflows", "oneil-cup-nonoverlap.yml")
    wf = yaml.safe_load(open(p))
    assert wf["jobs"]["run"]["strategy"]["matrix"]["shard"] == [0, 1, 2]
    body = open(p).read()
    assert "scripts/oneil_cup_nonoverlap.py run" in body and "scripts/oneil_cup_nonoverlap.py merge" in body
