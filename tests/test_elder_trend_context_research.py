import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_trend_context_research as g  # noqa: E402
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


def test_weekly_gate_uses_completed_weeks_only():
    df = synth(300, 5)
    w1 = g.weekly_up(df)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("Close")] *= 3      # change the last bar only
    assert (g.weekly_up(df2).iloc[:-1] == w1.iloc[:-1]).all()


@pytest.mark.parametrize("fam", g.FAMILIES)
def test_family_runs_both_directions(fam):
    aggs = {}
    for seed in (1, 2, 3):
        g.run_symbol(synth(900, seed), fam, "1d", aggs)
    for _, _, fn, _ in g.variant_specs(fam):
        sig = fn(synth())
        assert all(len(sig[k]) == 500 for k in ("long", "short", "exit_long", "exit_short"))
    assert aggs and all(a["n"] > 0 for a in aggs.values())
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
