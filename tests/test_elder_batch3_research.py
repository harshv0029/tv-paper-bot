import ast
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_batch3_research as b  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(b.__file__).read())


def test_tags_unique_lowercase():
    seen = set()
    for fam in b.SIG_FAMILIES:
        for variant, params, _ in b.variant_specs(fam):
            for d in ("long", "short"):
                for am in b.er.ATR_MULTS:
                    t = b.er.make_tag(fam, variant, d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


@pytest.mark.parametrize("fam", ["osc", "struct", "chan"])
def test_family_runs_both_directions(fam):
    aggs = {}
    for seed in (1, 2, 3):
        b.run_symbol(synth(900, seed), fam, "1d", aggs)
    for variant, params, fn in b.variant_specs(fam):
        sig = fn(synth())
        for k in ("long", "short", "exit_long", "exit_short", "stop_long", "tgt_short"):
            assert len(sig[k]) == 500
    assert aggs and all(a["n"] > 0 for a in aggs.values())
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)


def test_orb_intraday_only_and_runs():
    with pytest.raises(ValueError):
        b.v_orb(synth())
    n_days, per = 30, 75
    rng = np.random.default_rng(5)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=15 + 5 * k)
                            for d in pd.bdate_range("2024-01-01", periods=n_days) for k in range(per)])
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
    df = pd.DataFrame({"Open": c, "High": c * 1.001, "Low": c * 0.999, "Close": c,
                       "Volume": np.full(len(idx), 1000.0)}, index=idx)
    sig = b.v_orb(df, 2)
    assert sig["long"].sum() <= n_days and sig["short"].sum() <= n_days
    aggs = {}
    b.run_symbol(df, "orb", "5m", aggs)
    assert aggs


def test_sim2_always_has_stop_and_target():
    df = synth(300, 4)
    ent = np.zeros(300, bool)
    ent[50] = True
    tr = b.sim2(df, ent, "long", 2.0, tgt_lvl=np.full(300, df["Close"].iloc[50] * 3))
    assert tr and tr[0]["reason"] in ("stop_loss", "max_hold_timeout", "target")


def test_trendline_and_divergence():
    x = np.r_[np.linspace(10, 5, 20), [8, 6.5, 7, 6, 5.5, 5.2], np.linspace(5, 9, 15)]
    up, dn = b.trendline_break(x, 2)
    assert up.shape == dn.shape == x.shape
    d = synth(300, 7)
    cls = b.div_classes(d["High"].to_numpy(), d["Low"].to_numpy(), np.random.default_rng(1).normal(size=300))
    assert set(cls) == {"a", "b", "c"}


def test_sizing_and_best_f():
    R = np.array([2, -1, 1.5, -1, 3, -1, -1, 2.5, 1, -1] * 5, float)
    f, worst = b.best_f(R)
    assert 0 < f <= 0.5 and worst == 1.0
    for pol in b.POLICIES:
        eq, dd = b.run_account(R, pol, f, worst)
        assert eq >= 0 and 0 <= dd <= 1
    aggs = {}
    for seed in (1, 2):
        b.run_sizing_symbol(synth(900, seed), "1d", aggs)
    assert aggs and all(k.startswith("sizing::") for k in aggs)


def test_breadth_pipeline():
    states = []
    for sh in range(2):
        st = {}
        for seed in (1 + sh * 5, 2 + sh * 5, 3 + sh * 5):
            b.breadth_accumulate(synth(900, seed), st)
        states.append(st)
    bd = b.breadth_merge_states(states)
    assert {"adv", "dec", "nh", "nl", "nft", "mas"} <= set(bd.columns)
    idx = synth(900, 99)
    sigs = b.breadth_signals(idx, bd)
    assert {"ad_confirm", "nhnl_turn", "trin13_bull", "climax", "mas_diverge", "nhnl_trin_combo"} <= set(sigs)
    aggs = b.breadth_trade(idx, bd)
    assert all(t.startswith("breadth__") for t in aggs)
