"""B-1467: main.py port of the Minervini lab exits/filters vs the research harness (scripts/minervini_lab.py,
scripts/b412_helpers.simulate_lab_exit) on synthetic data, plus short-mirror unit checks and replay-job smoke."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import main as m  # noqa: E402
import minervini_lab as lab  # noqa: E402
import b412_helpers as H  # noqa: E402
import minervini_lab_main_replay_job as J  # noqa: E402

COST = m.ROUND_TRIP_COST_PCT / 100.0
NON_REGIME = [v for v in m.MINERVINI_LAB_EXIT_VARIANTS if not v.startswith("regime")]


def _frame(seed, n=700):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.012, n))
    # occasional large gaps so gap/climax exits fire
    gap = rng.random(n) < 0.03
    o[gap] = c[gap] * (1 + rng.choice([-0.08, 0.08], gap.sum()))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = rng.integers(1e5, 1e6, n).astype(float)
    return pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v},
                        index=pd.bdate_range("2021-01-01", periods=n))


def _sigs(df, rng, k=25):
    c = df["Close"].to_numpy(float)
    out = []
    for i in sorted(rng.choice(np.arange(210, len(df) - 2), k, replace=False)):
        out.append((int(i), float(c[i]), float(c[i]) * rng.uniform(0.85, 0.97), float(c[i]) * rng.uniform(0.01, 0.04)))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_exit_parity_vs_lab_run_variant_and_b412(seed):
    df = _frame(seed)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    ones = np.ones(len(df), bool)
    rng = np.random.default_rng(seed + 100)
    reasons = set()
    for sg in _sigs(df, rng):
        for v in m.MINERVINI_LAB_EXIT_VARIANTS:
            ref = lab.run_variant(v, df, sg, ones, COST)
            got = m.minervini_lab_simulate_trade(v, o, h, l, c, sg, "long")
            if ref is None:
                assert got is None
                continue
            x, px, held, reason, ent = got
            assert held == ref[1], (v, sg)
            assert px / ent - 1 - COST == pytest.approx(ref[0], abs=1e-12), (v, sg)
            reasons.add(reason)
            if v in NON_REGIME:
                b = H.simulate_lab_exit(v, o, h, l, c, sg, COST)
                exp = "end_of_data" if (b[2] == "max_hold_timeout" and sg[0] + 1 + 60 > len(c)) else b[2]
                assert reason == exp and held == b[1], (v, sg, reason, b)
    assert {"stop_hit", "max_hold_timeout"} <= reasons


def test_regime_variant_is_base_exit():
    df = _frame(7)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    for sg in _sigs(df, np.random.default_rng(7)):
        assert m.minervini_lab_simulate_trade("regime_nifty50", o, h, l, c, sg) == m.minervini_lab_simulate_trade("base", o, h, l, c, sg)


@pytest.mark.parametrize("seed", [4, 5])
def test_features_parity(seed):
    df = _frame(seed)
    idx = _frame(seed + 50)["Close"].to_numpy(float)
    for i in range(260, 690, 37):
        for rs, nn in ((None, False), (75.0, True), (40.0, False)):
            assert m.minervini_lab_features(df, i, idx, rs, nn) == lab.features(df, i, idx, rs, nn)
    assert set(m.minervini_lab_features(df, 300, idx, None, False)) == set(m.MINERVINI_LAB_FEATURE_NAMES)


def test_panels_and_cluster():
    frames = {f"S{k}": _frame(k, 400) for k in range(5)}
    cl = pd.DataFrame({s: f["Close"] for s, f in frames.items()})
    hi = pd.DataFrame({s: f["High"] for s, f in frames.items()})
    lo = pd.DataFrame({s: f["Low"] for s, f in frames.items()})
    rs, nn = m.minervini_lab_rs_nhnl_panels(cl, hi, lo)
    blend = 0.4 * (cl / cl.shift(63) - 1) + 0.2 * (cl / cl.shift(126) - 1) + 0.2 * (cl / cl.shift(189) - 1) + 0.2 * (cl / cl.shift(252) - 1)
    pd.testing.assert_frame_equal(rs, blend.rank(axis=1, pct=True) * 100)
    assert nn.dtype == bool and len(nn) == len(cl)
    assert m.minervini_lab_stopout_cluster_flags([-1, -1, 1, -1, 1, 0.5, 2]) == [False] * 5 + [True, False]
    assert m.minervini_lab_stopout_cluster_flags([1, 1, 1, 1, -1, -1]) == [False] * 6


def test_parse_variant():
    assert m.minervini_lab_parse_variant("pct8_hard_f_ext_le5_on") == ("pct8_hard", "ext_le5", "on")
    assert m.minervini_lab_parse_variant("pct8_hard_f_after_stopout_cluster_off") == ("pct8_hard", "after_stopout_cluster", "off")
    assert m.minervini_lab_parse_variant("rr3") == ("rr3", None, None)


def _flat(n=300, px=100.0):
    a = np.full(n, px)
    return a.copy(), a * 1.001, a * 0.999, a.copy()


def test_short_mirror_rules():
    o, h, l, c = _flat()
    mas = m.minervini_lab_moving_averages(c)
    # pct8_hard short stop sits 8% above the fill
    assert m.minervini_lab_initial_stop("pct8_hard", 100.0, 110.0, "short") == pytest.approx(108.0)
    assert m.minervini_lab_initial_stop("cap10_struct", 100.0, 120.0, "short") == pytest.approx(110.0)
    assert m.minervini_lab_open_position("base", 100.0, 99.0, 1.0, 100.0, 1, "short") is None  # stop below a short fill
    # stop hit: a spike above the stop
    h2 = h.copy(); h2[230] = 111.0
    r = m.minervini_lab_simulate_trade("base", o, h2, l, c, (220, 100.0, 105.0, 1.0), "short", mas=mas)
    assert r[3] == "stop_hit" and r[1] == pytest.approx(max(min(105.0, 100 + 2 * 1.0), o[230]))
    # rr2 target below entry
    l3 = l.copy(); l3[225] = 80.0
    r = m.minervini_lab_simulate_trade("rr2", o, h, l3, c, (220, 100.0, 105.0, 1.0), "short", mas=mas)
    assert r[3] == "target_hit" and r[1] == pytest.approx(90.0)
    # gap up exit at the open
    o4, h4 = o.copy(), h.copy(); o4[226] = 106.0; h4[226] = 106.5
    r = m.minervini_lab_simulate_trade("gap_dn_exit", o4, h4, l, c, (220, 100.0, 110.0, 1.0), "short", mas=mas)
    assert r[3] == "gap_up_exit" and r[1] == pytest.approx(106.0)
    # flat market: max hold at 60 bars
    r = m.minervini_lab_simulate_trade("pct8_hard", o, h, l, c, (220, 100.0, 110.0, 1.0), "short", mas=mas)
    assert r[3] == "max_hold_timeout" and r[2] == 60


def test_tags_follow_grammar():
    t = J.new_tag("pct8_hard_f_dryup_on", "short")
    assert t == "minervini_vcp__pct8_hard_f_dryup_on_srcmain__short__1d__h60__v1"
    assert J.source_tag("rr3", "long") == "minervini_vcp__rr3__long__1d__h60__v1"
    parts = t.split("__")
    assert len(parts) == 6 and parts[2] in ("long", "short") and parts[3] == "1d"
    with pytest.raises(SystemExit):
        J.job_spec("1d")


def test_replay_job_one_position_per_symbol():
    df = _frame(9)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    arrs = (o, h, l, c, m.minervini_lab_moving_averages(c))
    sigs = J.baseline_signals(df, "long")
    tr = J.walk(m, "pct8_hard", df, arrs, sigs, "long", COST)
    ent_pos = [df.index.get_loc(t["entry_date"]) for t in tr]
    for a, b, t in zip(ent_pos, ent_pos[1:], tr):
        assert b > a + t["held"] - 1  # next entry strictly after the previous exit bar
    assert all(t["net"] == pytest.approx(t["gross"] - COST) for t in tr)


def test_replay_job_synthetic_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("SYMBOL_LIMIT", "3")
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    out = J.run("baseline_short")
    assert out["synthetic"] and out["one_position_per_symbol"]
    assert (tmp_path / "minervini_lab_main_replay_baseline_short.json").exists()
    for tag, r in out["rows"].items():
        assert "_srcmain__short__" in tag
        mt = r["metrics"]
        for k in ("n", "pfnet", "pfgross", "win_pct", "avg_held_bars", "oos_pfnet", "exit_reasons", "is", "oos"):
            assert k in mt


def test_port_is_unwired():
    src = open(os.path.join(ROOT, "main.py")).read()
    # defined once, never called from main.py outside the port's own functions
    assert src.count("minervini_lab_simulate_trade(") == 1
    assert "minervini_lab" not in str(m._STRATEGY_TAG_TO_REGISTRY_NAME)
