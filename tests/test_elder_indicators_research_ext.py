import ast
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_indicators_research_ext as ex  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "elder_indicators_research_ext.py")


def test_script_parses():
    ast.parse(open(SCRIPT).read())


def test_tags_unique_lowercase():
    seen = set()
    for fam in ex.FAMILIES:
        for variant, params, _, _ in ex.variant_specs(fam):
            for d in ("long", "short"):
                for am in ex.er.ATR_MULTS:
                    t = ex.er.make_tag(fam, variant, d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


def test_indicator_ranges():
    df = synth()
    r = ex.williams_r(df).dropna()
    assert r.min() >= -1e-9 and r.max() <= 100 + 1e-9
    k, d = ex.stoch_slow(df)
    assert k.dropna().between(-1e-6, 100 + 1e-6).all()
    assert ex.rsi_wilder(df["Close"]).dropna().between(0, 100).all()
    _, t = ex.parabolic_sar(df)
    assert set(np.unique(t)) <= {-1.0, 0.0, 1.0}


@pytest.mark.parametrize("fam", ex.FAMILIES)
def test_family_runs(fam):
    df = synth(600, seed=3)
    aggs = {}
    ex.run_symbol(df, fam, "1d", aggs)
    for _, _, fn, _ in ex.variant_specs(fam):
        sig = fn(df)
        for k in ("long", "short", "exit_long", "exit_short", "long_lvl", "short_lvl"):
            assert len(sig[k]) == len(df)
    assert aggs, fam
    assert any("__long__" in t for t in aggs) or any("__short__" in t for t in aggs)
