import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import gap_fade_confirm as gf  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses_and_specs():
    ast.parse(open(gf.__file__).read())
    s = gf.specs()
    assert len(s) == 6 and {x[0] for x in s} == set(gf.VARIANTS)


def test_run_symbol_emits_v2_tags_with_gross():
    aggs = {}
    gf.run_symbol(gf.er.prep(synth()), "1d", aggs)
    assert all(t.endswith("__v2") and t.startswith("gaps__") for t in aggs)
    assert all("gwin_sum" in a for a in aggs.values())


def test_v2_tags_do_not_collide_with_registered():
    import strategy_registry as sr
    names = {s.name for s in sr.REGISTRY}
    t = gf.er.make_tag("gaps", "exhaust_fade", "long", "1d", {"nb": 5, "atr": 3.0}, version=2)
    assert t not in names


def test_fifo_and_is_oos_segments():
    aggs = {}
    gf.run_symbol(gf.er.prep(synth(900, 3)), "1d", aggs)
    checked = 0
    for t in list(aggs):
        if "segis" in t:
            base, oos = t.replace("_segis", ""), t.replace("segis", "segoos")
            assert base in aggs and oos in aggs
            assert aggs[t]["n"] + aggs[oos]["n"] == aggs[base]["n"]
            checked += 1
    assert checked > 0


def test_fifo_filter_drops_overlap():
    tr = [{"s": 1, "hold": 5}, {"s": 3, "hold": 2}, {"s": 7, "hold": 2}]
    out = gf.fifo_filter(tr)
    assert [x["s"] for x in out] == [1, 7] and gf.has_overlap(tr) and not gf.has_overlap(out)


def test_merge_path_reports_universe(tmp_path):
    import json
    aggs = {}
    gf.run_symbol(gf.er.prep(synth(900, 3)), "1d", aggs)
    json.dump({"fetched": 1, "universe": 1, "aggs": aggs}, open(tmp_path / "gapfade_0.json", "w"))
    out = tmp_path / "r.json"
    assert gf.main(["--merge", str(tmp_path), "--json", str(out)]) == 0
    assert json.load(open(out))["universe_size"] == 1
