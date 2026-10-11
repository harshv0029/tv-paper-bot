import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import douglas_trade_mgmt_research as g  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(g.__file__).read())


def test_tags_unique_lowercase():
    seen = set()
    for fam in g.FAMILIES:
        for variant, params, _, _ in g.variant_specs(fam):
            for d in ("long", "short"):
                for am in g.er.ATR_MULTS:
                    t = g.er.make_tag(g.TAGFAM[fam], variant, d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


def test_every_trade_has_a_bounded_loss():
    """Stop on every trade: no cell may show a loss beyond a stop plus a generous gap allowance."""
    df = synth(900, 2)
    sig = g.b_dip(df)
    for d in ("long", "short"):
        for t in g.sim_r(df, sig, d, 2.0, {}):
            assert t["ret"] > -0.45


def test_management_options_run():
    df = synth(900, 3)
    sig = g.b_dip(df)
    for opt in ({"be_r": 1.0}, {"scale": "atr"}, {"scale": "struct", "buf": 0.1}, {"pyramid": 0.025},
                {"limit": 3}, {"chase": 0.25}, {"min_rr": 2.0}, {"max_hold": 5}, {"cooldown": 6}):
        tr = g.sim_r(df, sig, "long", 2.0, opt)
        assert all(t["hold"] >= 1 for t in tr)


@pytest.mark.parametrize("fam", g.FAMILIES)
def test_family_runs_both_directions(fam):
    aggs = {}
    for seed in (1, 2, 3):
        g.run_symbol(synth(900, seed), fam, "1d", aggs)
    assert aggs and all(a["n"] > 0 for a in aggs.values())
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    s = g.summarize(next(iter(aggs.values())))
    assert "losers_reached_1r_pct" in s and "pf_gross" in s
