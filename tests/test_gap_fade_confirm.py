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
