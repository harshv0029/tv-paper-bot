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


def test_simulate_target_and_sr_tighten():
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    base = np.full(40, 100.0)
    df = pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1, "Close": base, "Volume": 1e6}, index=idx)
    df.iloc[25:, df.columns.get_loc("High")] = 130.0
    df.iloc[25:, df.columns.get_loc("Close")] = 125.0
    n = len(df)
    ent = np.zeros(n, bool)
    ent[20] = True
    z = np.zeros(n, bool)
    sig = g.er._pack(df, ent, z, z, z)
    sig["long_tgt"] = np.where(ent, 110.0, np.nan)
    tr = g.er.simulate(df, sig, "long", 3.0)
    assert tr[0]["reason"] == "target_hit" and tr[0]["ret"] > 0.05
    sig2 = g.er._pack(df, ent, z, z, z)
    sig2["long_sr"] = np.where(ent, 101.0, np.nan)
    tr2 = g.er.simulate(df, sig2, "long", 3.0, {"sr_atr": 0.5, "sr_trail_atr": 1.0})
    assert tr2


def test_new_variants_present_and_both_x_keys():
    names = {v for fam in g.FAMILIES for v, _, _, _ in g.variant_specs(fam)}
    assert {"tl_break_mm", "edge_bounce_srtight"} <= names
    sig = g.both_x(g.d_tl_break_mm)(synth(900, 5))
    assert "long_tgt" in sig and "short_tgt" in sig
    sig = g.both_x(g.d_edge_bounce_sr)(synth(900, 5))
    assert "long_sr" in sig and "short_sr" in sig
