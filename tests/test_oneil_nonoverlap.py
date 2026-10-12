import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import oneil_ext_research as ox
import oneil_nonoverlap as on
import oneil_research as orx


def _series(n=400, seed=5):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    return o, h, l, c, np.full(n, 1e6)


def test_independent_then_fifo_is_non_overlapping_and_matches_simulate_x():
    o, h, l, c, v = _series()
    n = len(c)
    atr = orx.atr_arr(h, l, c)
    sig = np.zeros(n, bool)
    sig[60:300] = True  # signal on every bar -> massive overlap before the filter
    ex = ox.EX["1d"]
    kept, raw = on.nonovl_trades(sig, o, h, l, c, v, atr, 20, 3.0, "base", 0, None, 1, 0.008, ex)
    assert raw > len(kept) > 0
    assert not on.no.has_overlap(kept)
    ref = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "base", 0, None, 1, 0.008, ex)
    assert len(ref) == len(kept)
    assert [round(r[0], 9) for r in ref] == [round(t["net"], 9) for t in kept]


def test_agg_summary_split_and_top5_trim():
    a = on.new_agg()
    tr = [{"entry_i": i, "exit_i": i, "net": x, "gross": x + 0.008, "hold": 5, "reason": "stop"}
          for i, x in enumerate([-0.1] * 8 + [0.5, 0.4, 0.3, 0.2, 0.1, 0.05])]
    on.add_trades(a, tr, "AAA", pd.date_range("2024-01-01", periods=20, freq="D"))
    s = on.summarize(a)
    assert s["n"] == 14 and s["win_pct"] == round(100 * 6 / 14, 1)
    assert s["pfnet"] == round(1.55 / 0.8, 3)
    assert abs(s["pfnet_ex_top5"] - 0.05 / 0.8) < 0.001  # global top-5 winners removed
    b = on.new_agg()
    on.merge_agg(b, a)
    on.merge_agg(b, a)
    assert b["n"] == 28 and on.summarize(b)["pfnet"] == s["pfnet"]


def test_run_symbol_emits_nonovl_and_segment_tags_without_overlap():
    o, h, l, c, v = _series(500, seed=11)
    idx = pd.date_range("2022-01-03", periods=500, freq="B")
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)
    df.name = "SYN"
    rs = pd.Series(50.0, index=idx)
    aggs, raw = {}, {}
    on.run_symbol(df, None, rs, orx.CFG["1d"], ox.EX["1d"], 0.008, "1d", ["pivot_tight", "leaders", "exit_six"], aggs, raw)
    for tag, a in aggs.items():
        assert ("nonovl" in tag) and tag.endswith("__v2")
    segs = [t for t in aggs if "_nonovl_seg" in t]
    for t in aggs:
        if t.endswith("_nonovl__v2") or "__nonovl__v2" in t:
            base = t[:-len("__nonovl__v2")]
            n_is = aggs.get(base + "_nonovl_segis__v2", on.new_agg())["n"]
            n_oos = aggs.get(base + "_nonovl_segoos__v2", on.new_agg())["n"]
            assert n_is + n_oos == a_n(aggs[t])
            assert raw[t] >= aggs[t]["n"]
    assert segs or not aggs


def a_n(a):
    return a["n"]


def test_tags_match_registry_style():
    spec = on.CELL_SETS["pivot_tight"][0]
    tag, hold = on.cell_tag(spec, "1d", "long", ox.EX["1d"], orx.CFG["1d"]["holds"])
    assert tag == "oneil_pivot__breakout__long__1d__atr3_chase10_h40__v1__x__oneil_tightness__range__long__1d__pr1__v1"
    assert hold == 40
    stag, sh = on.cell_tag(on.CELL_SETS["shake1w"][0], "1w", "short", ox.EX["1w"], orx.CFG["1w"]["holds"])
    assert stag == "oneil_shakeout__plus3__short__1w__atr2_h8_pm2__v1" and sh == 8
    xtag, xh = on.cell_tag(on.CELL_SETS["exit_six"][0], "1d", "long", ox.EX["1d"], orx.CFG["1d"]["holds"])
    assert xtag == "oneil_pivot__exit__long__1d__atr3_chase10_h130_xmsix125__v1" and xh == 130
