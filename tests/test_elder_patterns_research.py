import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_patterns_research as g  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(g.__file__).read())


def test_tags_unique_lowercase():
    seen = set()
    for fam in g.FAMILIES:
        for variant, params, _, _ in g.variant_specs(fam):
            for d in ("long", "short"):
                for am in g.er.ATR_MULTS:
                    t = g.er.make_tag(fam, variant, d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


def test_flip_is_involution_and_keeps_high_above_low():
    df = synth(100, 4)
    f = g.flip(g.flip(df))
    assert abs(f["Close"] - df["Close"]).max() < 1e-9
    assert (g.flip(df)["High"] >= g.flip(df)["Low"]).all()


@pytest.mark.parametrize("fam", g.FAMILIES)
def test_family_runs_both_directions(fam):
    aggs = {}
    for seed in (1, 2, 3):
        g.run_symbol(synth(900, seed), fam, "1d", aggs)
    for _, _, fn, _ in g.variant_specs(fam):
        sig = fn(synth())
        for k in ("long", "short", "exit_long", "exit_short"):
            assert len(sig[k]) == 500
    assert aggs and all(a["n"] > 0 for a in aggs.values())
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
