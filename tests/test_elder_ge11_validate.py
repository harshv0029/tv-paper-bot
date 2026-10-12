import ast
import json
import os
import re
import sys

R = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(R, "scripts"))
sys.path.insert(0, R)
sys.path.insert(0, os.path.dirname(__file__))
import elder_ge11_validate as ge  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses_and_cells():
    ast.parse(open(ge.__file__).read())
    w = ge.wanted()
    assert {(f, v) for f, v, *_ in w} == {("gaps", "exhaust_fade"), ("gaps", "common_fade"), ("macd", "hist_exhaust")}
    assert len(w) == 7


def test_run_symbol_tags_segments_and_fifo_equal():
    aggs = {}
    ge.run_symbol(ge.er.prep(synth(900, 3)), "1d", aggs)
    assert aggs and all(t.endswith("__v3") for t in aggs)
    pooled = [t for t in aggs if not ge.is_seg_tag(t)]
    assert pooled
    for t in pooled:
        a = aggs[t]
        assert a["raw_n"] == a["n"]  # er.simulate is already one position per symbol
        assert aggs[ge.seg_tag(t, "is")]["n"] + aggs[ge.seg_tag(t, "oos")]["n"] == a["n"]
        assert aggs[ge.seg_tag(t, "bull")]["n"] + aggs[ge.seg_tag(t, "bear")]["n"] <= a["n"]


def test_summarize_has_trim5():
    a = ge.new_agg()
    rets = [0.5, 0.4, 0.3, 0.2, 0.1, 0.05, -0.1]
    ge.er.add_trades(a, [{"ret": r, "hold": 2, "reason": "x", "s": i} for i, r in enumerate(rets)])
    s = ge.er.summarize(a)
    assert s["pfnet_trim5"] is not None and s["pfnet_trim5"] < s["pfnet_trim1"] < s["pfnet"]


def test_verdict_requires_oos_n_and_trim5():
    base = "gaps__exhaust_fade__long__1d__atr3_nb5__v3"

    def row(t, **k):
        return {"tag": t, "pfnet": 1.3, "pfnet_trim5": 1.2, "n": 100, "raw_n": 100, **k}
    rows = [row(base), row(ge.seg_tag(base, "oos"), n=29), row(ge.seg_tag(base, "bear"))]
    assert not ge.verdicts(rows, 1.1)[0]["confirmed"]
    rows[1]["n"] = 30
    assert ge.verdicts(rows, 1.1)[0]["confirmed"]
    rows[1]["pfnet_trim5"] = 1.0
    assert not ge.verdicts(rows, 1.1)[0]["confirmed"]


def test_merge_roundtrip(tmp_path):
    aggs = {}
    ge.run_symbol(ge.er.prep(synth(900, 3)), "1d", aggs)
    json.dump({"fetched": 1, "universe": 1, "aggs": aggs, "fetched_symbols": ["A.NS"]},
              open(tmp_path / "ge11_0.json", "w"))
    res = ge.merge(str(tmp_path))
    assert res["symbols_fetched"] == 1 and res["fetched_symbols"] == ["A.NS"] and res["verdicts"]


def test_workflow_static():
    txt = open(os.path.join(R, ".github/workflows/elder-ge11-validate.yml")).read()
    assert "workflow_dispatch" in txt and "upload-artifact" in txt and "elder_ge11_validate.py" in txt
    assert len(re.findall(r"\d", re.search(r"shard: \[(.*?)\]", txt).group(1))) + 1 <= 40
    assert "_load_nse_universe_from_file()" in open(ge.__file__).read()
