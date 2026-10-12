import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import island_validation as iv
import macddiv_nonoverlap as no
import test_island_validation as tiv


def test_split_ts_and_segmentation_partition():
    idx = pd.date_range("2021-01-01", periods=100)
    assert no.split_ts(idx, "2021-02-01") == pd.Timestamp("2021-02-01")
    assert no.split_ts(idx, "", 0.5) == idx[0] + (idx[-1] - idx[0]) * 0.5
    tr = [{"entry_i": i, "exit_i": i} for i in (5, 40, 49, 50, 90, 200)]
    ins, oos = no.segment_trades(tr, idx, no.split_ts(idx, "", 0.5))
    assert len(ins) + len(oos) == len(tr) and ins and oos


def test_seg_tags_follow_spec():
    old = "macddiv__line_any__long__1h__atr3_w5__v1"
    assert no.seg_tag(old, "is") == "macddiv__line_any__long__1h__atr3_w5_nonovl_segis__v2"
    assert no.seg_tag(old, "oos").endswith("_nonovl_segoos__v2")
    o = "reversal__island_gap05__long__1d__atr3_within8__v1"
    assert iv.nonovl_seg_tag(o, "is") == "reversal__island_gap05__long__1d__atr3_within8__segis__v2"
    assert no.nonovl_tag(o) == "reversal__island_gap05__long__1d__atr3_within8__nonovl__v2"


def test_island_nonovl_cells_sum_to_pooled_and_are_long_only():
    aggs = {}
    iv.run_symbol_nonovl(tiv._df(), "1d", aggs, "", 0.5)
    assert aggs and all("__long__" in t and t.islower() and t.endswith("__v2") for t in aggs)
    for t, a in aggs.items():
        if t.endswith("__nonovl__v2"):
            base = t[:-len("__nonovl__v2")]
            assert a["n"] == aggs[base + "__segis__v2"]["n"] + aggs[base + "__segoos__v2"]["n"]
            s = iv.summarize(a)
            assert {"pfnet", "pf_gross", "win_pct", "n", "avg_hold_bars", "avg_net_ret_pct", "exit_reasons",
                    "by_year"} <= set(s)
    assert any(a["n"] for a in aggs.values())


def test_workflows_expose_split_inputs_and_flags():
    for wf, sc in (("island-validation", "island_validation"), ("macddiv-nonoverlap", "macddiv_nonoverlap")):
        txt = open(os.path.join(HERE, "..", ".github", "workflows", wf + ".yml")).read()
        src = open(os.path.join(HERE, "..", "scripts", sc + ".py")).read()
        for inp in ("split_date", "split_frac"):
            assert f"{inp}:" in txt and f'"--{inp}"' in src and f"--{inp}" in txt
        shards = re.search(r"shard: \[(.*?)\]", txt).group(1).split(",")
        assert len(shards) + 1 <= 38
