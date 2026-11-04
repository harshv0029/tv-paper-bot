"""B-1463: main.py's ported O'Neil ext detectors equal the research bull_signals (both directions), are walk-forward,
the main-calling non-overlap exit equals simulate_x 'base', and nothing is wired live."""
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import main as app  # noqa: E402
import oneil_ext_research as ox  # noqa: E402
import oneil_nonoverlap as on  # noqa: E402
import oneil_research as orx  # noqa: E402

PORTED = ("oneil_hft", "oneil_shakeout", "oneil_hns", "oneil_triple", "oneil_trendline", "oneil_tightarea",
          "oneil_pullback", "oneil_rsline", "oneil_leaders", "oneil_volpct")


def _series(seed, n=700, vol=0.02, drift=0.0008):
    rng = np.random.default_rng(seed)
    ret = rng.normal(drift, vol, n)
    # regime swings so bases, pullbacks, H&S-like troughs and new highs all occur
    ret += 0.01 * np.sin(np.arange(n) / 17.0) + 0.006 * np.sin(np.arange(n) / 53.0)
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = 1e6 * np.exp(rng.normal(0, 0.5, n))
    v[rng.random(n) < 0.08] *= 8.0
    idx = 1e4 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n) + 0.004 * np.sin(np.arange(n) / 40.0)))
    rs = np.clip(50 + 45 * np.sin(np.arange(n) / 30.0 + seed), 1, 99)
    return o, h, l, c, v, idx, rs


SEEDS = range(12)


def _research(d, tf, o, h, l, c, v, idx, rs):
    arrs = (o, h, l, c, idx, rs) if d == "long" else ox.mirror(o, h, l, c, idx, rs)
    E, _brk, _F, _X = ox.bull_signals(arrs[0], arrs[1], arrs[2], arrs[3], v, arrs[4], arrs[5], orx.CFG[tf], ox.EX[tf])
    return E


@pytest.mark.parametrize("tf", ["1d", "1w"])
@pytest.mark.parametrize("d", ["long", "short"])
def test_main_equals_research_every_family(tf, d):
    fired = {}
    for seed in SEEDS:
        o, h, l, c, v, idx, rs = _series(seed)
        ref = _research(d, tf, o, h, l, c, v, idx, rs)
        got = app.oneil_ext_signals(d, tf, o, h, l, c, v, idx, rs)
        for k, arr in ref.items():
            if k[0] not in PORTED:
                continue
            assert k in got, k
            assert np.array_equal(arr, got[k]), (k, seed)
            fired[k[0]] = fired.get(k[0], 0) + int(arr.sum())
    assert set(fired) == set(PORTED)
    # parity is only meaningful if the synthetic data exercises the detectors
    assert sum(1 for f in PORTED if fired[f] > 0) >= 7, fired


@pytest.mark.parametrize("fam", PORTED)
def test_each_family_parity_long_and_short_mirror(fam):
    o, h, l, c, v, idx, rs = _series(3)
    for d in ("long", "short"):
        ref = {k: a for k, a in _research(d, "1d", o, h, l, c, v, idx, rs).items() if k[0] == fam}
        got = {k: a for k, a in app.oneil_ext_signals(d, "1d", o, h, l, c, v, idx, rs).items() if k[0] == fam}
        assert ref.keys() == got.keys() and ref
        for k in ref:
            assert np.array_equal(ref[k], got[k])


def test_short_is_long_detector_on_reciprocal_series():
    o, h, l, c, v, idx, rs = _series(5)
    mo, mh, ml, mc, mi, mr = app.oneil_ext_mirror(o, h, l, c, idx, rs)
    assert np.allclose(mh, 1 / l) and np.allclose(ml, 1 / h) and np.allclose(mr, 100 - rs)
    s = app.oneil_ext_signals("short", "1d", o, h, l, c, v, idx, rs)
    b = app.oneil_ext_bull_signals(mo, mh, ml, mc, v, mi, mr, "1d")
    for k, arr in b.items():
        assert np.array_equal(arr, s[k])
    # and the long detector on the mirrored series' mirror is the original long
    back = app.oneil_ext_signals("short", "1d", mo, mh, ml, mc, v, mi, mr)
    longs = app.oneil_ext_signals("long", "1d", o, h, l, c, v, idx, rs)
    for k in b:
        assert np.array_equal(back[k], longs[k])


def test_rsscreen_matches_research_entry_signals_both_sides(monkeypatch):
    o, h, l, c, v, idx, rs = _series(7, n=800, drift=0.0015)
    monkeypatch.setenv("PATTERNS", "0")
    ref = orx.entry_signals(o, h, l, c, v, rs, orx.CFG["1d"])
    long_m = app.oneil_ext_signals("long", "1d", o, h, l, c, v, idx, rs)[("oneil_rsscreen", "top", "rs90")]
    short_m = app.oneil_ext_signals("short", "1d", o, h, l, c, v, idx, rs)[("oneil_rsscreen", "top", "rs20")]
    assert np.array_equal(long_m, ref[("oneil_rsscreen", "top", "long", None, "90")])
    assert np.array_equal(short_m, ref[("oneil_rsscreen", "top", "short", None, "20")])
    assert long_m.any() or short_m.any()


def test_signal_at_is_walk_forward():
    o, h, l, c, v, idx, rs = _series(2, n=420)
    full = app.oneil_ext_signals("long", "1d", o, h, l, c, v, idx, rs)
    checked = 0
    for (fam, _var, pk), arr in full.items():
        for t in list(np.flatnonzero(arr)[:3]) + [300, 419]:
            assert app.oneil_ext_signal_at(fam, "long", "1d", int(t), o, h, l, c, v, idx, rs, pk) == bool(arr[t])
            checked += 1
    assert checked > 20
    assert app.oneil_ext_signal_at("oneil_nope", "long", "1d", 10, o, h, l, c, v) is False


def test_main_exit_equals_simulate_x_base_and_has_stop():
    o, h, l, c, v, idx, rs = _series(9)
    atr = app.oneil_atr14(h, l, c)
    sig = np.zeros(len(c), bool)
    sig[60:600:3] = True
    for side in (1, -1):
        for stopm in (2.0, 3.0):
            kept, raw = on.nonovl_trades_main(sig, o, h, l, c, atr, 20, stopm, side, 0.008)
            ref = ox.simulate_x(sig, o, h, l, c, v, atr, 20, stopm, "base", 0, None, side, 0.008, ox.EX["1d"])
            assert raw > len(kept) > 0
            assert [(round(r[0], 12), r[2], r[3]) for r in ref] == [(round(t["net"], 12), t["hold"], t["reason"]) for t in kept]
            assert not on.no.has_overlap(kept)
            assert {t["reason"] for t in kept} <= {"stop", "timeout"}


def test_ext_main_tags_grammar_and_run_symbol():
    cfg = orx.CFG["1d"]
    t, hold = on.cell_tag(("mainentry", "long", ("oneil_tightarea", "breakout", "r2"), 1, 3.0), "1d", "long", ox.EX["1d"], cfg["holds"])
    assert t == "oneil_tightarea__breakout__long__1d__atr3_h40_pr2_srcmain__v1" and hold == 40
    t, _ = on.cell_tag(("mainentry", "short", ("oneil_rsscreen", "top", "rs"), 0, 2.0), "1d", "short", ox.EX["1d"], cfg["holds"])
    assert on.no.nonovl_tag(t) == "oneil_rsscreen__top__short__1d__atr2_h20_rs20_srcmain__nonovl__v2"
    o, h, l, c, v, idx, rs = _series(4)
    dates = pd.bdate_range("2020-01-01", periods=len(c))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=dates)
    aggs, raw = {}, {}
    on.run_symbol(df, pd.Series(idx, index=dates), pd.Series(rs, index=dates), cfg, ox.EX["1d"], 0.008, "1d",
                  ["ext_main"], aggs, raw)
    full = [k for k in aggs if k.endswith("__nonovl__v2")]
    assert full and all("_srcmain_" in k or k.endswith("srcmain__nonovl__v2") for k in full)
    assert any("__long__" in k for k in full) and any("__short__" in k for k in full)
    aggs2, raw2 = {}, {}
    on.run_symbol(df, pd.Series(idx, index=dates), pd.Series(rs, index=dates), cfg, ox.EX["1d"], 0.008, "1d",
                  ["ext_main"], aggs2, raw2, families={"oneil_volpct"})
    assert aggs2 and all(k.startswith("oneil_volpct__") for k in aggs2)


def test_not_wired_live():
    src = (R / "main.py").read_text()
    for fn in ("oneil_ext_signals(", "oneil_ext_signal_at(", "oneil_ext_bull_signals(", "oneil_rsscreen_signals("):
        uses = src.count(fn) - src.count("def " + fn)
        # only internal calls between the ported functions themselves
        assert uses <= 3, (fn, uses)
    assert "oneil_ext_signal" not in src.split("def _oneil_swing_try_entry")[1].split("\ndef ")[0]
