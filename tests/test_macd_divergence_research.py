import ast
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import macd_divergence_research as md  # noqa: E402
import elder_macd_dirgap_research as old  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(md.__file__).read())


def test_parity_with_original_hist_div_w3():
    for seed in (1, 2, 3):
        df = synth(900, seed)
        a, b = md.v_macd_divergence(df, 3, "hist", True), old.v_macd_div(df, 3)
        for k in ("long", "short"):
            assert (np.asarray(a[k]) == np.asarray(b[k])).all()


def test_zero_filter_is_subset_and_no_lookahead():
    df = synth(900, 4)
    z = md.v_macd_divergence(df, 3, "hist", True)
    a = md.v_macd_divergence(df, 3, "hist", False)
    for k in ("long", "short"):
        assert not (np.asarray(z[k]) & ~np.asarray(a[k])).any()
    cut = md.v_macd_divergence(df.iloc[:600], 3, "hist", False)
    assert (np.asarray(cut["long"])[:590] == np.asarray(a["long"])[:590]).all()


def test_tags_unique_lowercase_both_directions_all_intervals():
    seen = set()
    for tf in md.PERIODS:
        for variant, params, _ in md.variant_specs():
            for d in ("long", "short"):
                for am in md.er.ATR_MULTS:
                    t = md.er.make_tag(md.FAMILY, variant, d, tf, {**params, "atr": am})
                    assert t == t.lower() and t not in seen and not t.startswith("macd__")
                    seen.add(t)
    assert len(seen) == len(md.PERIODS) * 6 * 2 * 3


def test_run_symbol_produces_long_and_short():
    aggs = {}
    for seed in (1, 2, 3, 5):
        md.run_symbol(synth(900, seed), "1d", aggs)
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    assert all(a["n"] > 0 for a in aggs.values())
