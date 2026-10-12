import ast
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import swing_min_rr_research as s  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(s.__file__).read())


def test_tags_unique_lowercase():
    seen = set()
    for e in s.ENTRIES:
        for suffix, params, _ in s.cells():
            for d in ("long", "short"):
                for am in s.er.ATR_MULTS:
                    t = s.er.make_tag(s.FAMILY, f"{e}_{suffix}", d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


def test_mirror_swaps_high_low():
    df = synth(50, 1)
    m = s.mirror(df.reset_index(drop=True))
    assert (m["High"] >= m["Low"]).all()
    assert np.allclose(m["High"], 1 / df["Low"].to_numpy())


def test_target_and_stop_bounds_and_nonoverlap():
    df = synth(900, 2)
    sig = np.zeros(len(df), bool)
    sig[50::3] = True
    for d in ("long", "short"):
        for opt in ({}, {"target": 2.0}, {"gate": 2.0}, {"gate": 4.0, "target": 4.0}):
            tr, _ = s.sim(df, sig, d, 2.0, opt)
            assert all(t["ret"] > -0.45 for t in tr)          # stop on every trade
            ends = [t["e"] + t["hold"] - 1 for t in tr]
            starts = [t["e"] for t in tr]
            assert all(starts[i + 1] > ends[i] for i in range(len(tr) - 1))   # strict non-overlap


def test_bad_bar_dropped():
    df = synth(300, 3)
    df.iloc[100, df.columns.get_loc("Close")] *= 5
    sig = np.zeros(len(df), bool)
    sig[95] = True
    tr, glitch = s.sim(df, sig, "long", 3.0, {})
    assert glitch == 1 and not tr


def test_summary_top5_and_merge():
    a, b = s.new_agg(), s.new_agg()
    df = synth(100, 1)
    for k, ag in enumerate((a, b)):
        s.add_trades(ag, [{"ret": 0.1 * (i + 1) + k, "hold": 2, "reason": "target", "e": i} for i in range(4)] +
                     [{"ret": -0.05, "hold": 1, "reason": "stop_loss", "e": 9}], "X.NS", df.index)
    s.merge_aggs(a, b)
    r = s.summarize(a)
    assert r["n"] == 10 and len(r["top5"]) == 5 and r["pfnet_ex_top5"] < r["pfnet"]


@pytest.mark.parametrize("entry", ["brk20", "order_block", "volume_profile", "gap_and_go", "minervini_vcp"])
def test_entries_run_with_real_main(entry):
    import main as mn
    aggs = {}
    for seed in (1, 2):
        s.run_symbol(synth(600, seed), entry, "1d", aggs, mn, "T.NS")
    assert all(t.startswith("swingminrr__") for t in aggs)


def test_target_fills_at_rr_for_both_directions():
    import pandas as pd
    idx = pd.bdate_range("2023-01-02", periods=80)
    base = np.full(80, 100.0)
    for d, drift in (("long", 1.0), ("short", -1.0)):
        c = base + drift * np.maximum(0, np.arange(80) - 40) * 1.0
        df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": 1e3}, index=idx)
        sig = np.zeros(80, bool)
        sig[40] = True
        tr, _ = s.sim(df, sig, d, 1.5, {"target": 1.5})
        assert tr and tr[0]["reason"] == "target"
        assert tr[0]["ret"] > 0
