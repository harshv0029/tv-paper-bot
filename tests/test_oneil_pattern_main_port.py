"""B-1472 b: main.py's ported O'Neil chart-pattern detectors (cup_handle / saucer / cup_nohandle / double_bottom) give
bit-identical signal arrays to scripts/oneil_patterns.pattern_signals for every family/variant/direction/chase/rs
filter, are walk-forward, the main-calling replay equals the research-calling replay, and nothing is wired live."""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import main as app  # noqa: E402
import oneil_patterns as op  # noqa: E402
import oneil_research as orx  # noqa: E402

spec = importlib.util.spec_from_file_location("oneil_replay_b1472", R / "scripts" / "oneil_replay.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def _series(seed, n, cycle):
    """Seeded random walk with slow regime cycles (bases, cups, double bottoms, inverted ones for shorts)."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0004, 0.018, n)
    ret += 0.012 * np.sin(np.arange(n) / cycle) + 0.006 * np.sin(np.arange(n) / (cycle * 3.1))
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.004, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = 1e6 * np.exp(rng.normal(0, 0.5, n))
    v[rng.random(n) < 0.10] *= 6.0
    rs = np.clip(50 + 49 * np.sin(np.arange(n) / 25.0 + seed), 1, 99)
    rs[:30] = np.nan
    return o, h, l, c, v, rs


def _path(segs, seed, start=100.0):
    """Piecewise cosine path [(bars, target_price)], seeded noise; returns closes."""
    rng = np.random.default_rng(seed)
    out, p = [], start
    for nb, tgt in segs:
        x = (1 - np.cos(np.linspace(0, np.pi, nb + 1)[1:])) / 2
        out += list(p + (tgt - p) * x)
        p = tgt
    c = np.asarray(out) * (1 + rng.normal(0, 0.002, len(out)))
    return c


# 1d / 1w planted layouts per family [(bars, target)]: base, pattern, 1-bar breakout, long tail
_PLANTS = {
    "1d": {
        "cup_handle": [(80, 100), (30, 75), (30, 98), (8, 93), (1, 101), (65, 104)],
        "saucer": [(80, 100), (70, 86), (70, 98), (8, 95), (1, 101), (65, 104)],
        "cup_nohandle": [(80, 100), (30, 76), (30, 98), (1, 101.5), (65, 104)],
        "double_bottom": [(80, 100), (20, 80), (15, 92), (20, 79), (3, 85), (3, 93), (65, 96)],
    },
    "1w": {
        "cup_handle": [(30, 100), (6, 76), (6, 98), (2, 94), (1, 101), (30, 104)],
        "saucer": [(30, 100), (12, 86), (12, 98), (2, 95), (1, 101), (30, 104)],
        "cup_nohandle": [(30, 100), (6, 76), (6, 98), (1, 101.5), (30, 104)],
        "double_bottom": [(30, 100), (5, 80), (4, 92), (5, 79), (2, 85), (2, 93), (30, 96)],
    },
}


def _planted(tf, fam, seed, short=False):
    """A planted long pattern; short=True is its reciprocal-price mirror (the short detector's input)."""
    rng = np.random.default_rng(seed + 1000)
    c = _path(_PLANTS[tf][fam], seed)
    n = len(c)
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.001, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    v = 1e6 * np.exp(rng.normal(0, 0.15, n))
    up = np.flatnonzero(np.diff(c) / c[:-1] > 0.02) + 1  # breakout-type jumps get a volume surge
    v[up] *= 4.0
    rs = np.clip(50 + 49 * np.sin(np.arange(n) / 25.0 + seed), 1, 99)
    if short:
        o, h, l, c = 1.0 / o, 1.0 / l, 1.0 / h, 1.0 / c
        rs = 100.0 - rs
    return o, h, l, c, v, rs


RANDOM = [("1d", s, 900, 12.0) for s in range(6)] + [("1w", s, 400, 3.0) for s in range(6)]
PLANTED = [(tf, fam, seed, sh) for tf in ("1d", "1w") for fam in _PLANTS[tf] for seed in range(5)
           for sh in (False, True)]


def _frames(tf=None):
    """Every test frame: seeded random walks + planted patterns (both mirrors). Yields (tf, o, h, l, c, v, rs)."""
    for t_, seed, n, cyc in RANDOM:
        if tf in (None, t_):
            yield (t_,) + _series(seed, n, cyc)
    for t_, fam, seed, sh in PLANTED:
        if tf in (None, t_):
            yield (t_,) + _planted(t_, fam, seed, sh)


CASES = list(range(len(RANDOM) + len(PLANTED)))


@pytest.mark.parametrize("i", CASES)
def test_pattern_signals_bit_identical(i):
    tf, o, h, l, c, v, rs = list(_frames())[i]
    ref = op.pattern_signals(o, h, l, c, v, rs, orx.CFG[tf], orx.CHASES, orx.RS_FILTERS)
    got = app.oneil_pattern_signals(o, h, l, c, v, rs, tf, orx.CHASES, orx.RS_FILTERS)
    assert set(ref) == set(got)
    for k in ref:
        assert got[k].dtype == bool and np.array_equal(ref[k], got[k]), k


@pytest.mark.parametrize("tf", ["1d", "1w"])
def test_every_family_direction_variant_covered(tf):
    """The parity above is not vacuous: every (family, dir, chase, rs) key fires somewhere in the seeded set."""
    seen = set()
    for _tf, o, h, l, c, v, rs in _frames(tf):
        seen |= {k for k, m in app.oneil_pattern_signals(o, h, l, c, v, rs, tf).items() if m.any()}
    for fam in app.ONEIL_PATTERN_FAMILIES:
        for d in ("long", "short"):
            for ch in orx.CHASES:
                for rsf in ("none",) + (("qual1",) if fam == "oneil_cup_handle" else ()):
                    assert (fam, "breakout", d, ch, rsf) in seen, (fam, d, ch, rsf)


def test_constants_match_research():
    for tf in ("1d", "1w"):
        for k, val in app.ONEIL_PATTERN_CFG[tf].items():
            assert orx.CFG[tf][k] == val, (tf, k)
    assert app.ONEIL_CUP_DEPTH == op.CUP_DEPTH and app.ONEIL_SAUCER_DEPTH == op.SAUCER_DEPTH
    assert app.ONEIL_HANDLE_MAX_DROP == op.HANDLE_MAX_DROP
    assert app.ONEIL_PATTERN_CHASES == orx.CHASES and app.ONEIL_PATTERN_RS_FILTERS == orx.RS_FILTERS


@pytest.mark.parametrize("tf", ["1d", "1w"])
def test_signal_at_is_walk_forward(tf):
    """oneil_signal_at(t) sees bars <= t (+ o[t+1] for the chase) and equals the full-array value at t, at every
    hit bar and at random non-hit bars, for every emitted (family, dir, chase, rs) key."""
    checked = set()
    for i, (_tf, o, h, l, c, v, rs) in enumerate(_frames(tf)):
        n = len(c)
        full = app.oneil_pattern_signals(o, h, l, c, v, rs, tf)
        rng = np.random.default_rng(i)
        for (fam, _var, d, ch, rsf), arr in full.items():
            for t in list(np.flatnonzero(arr)[:2]) + list(rng.integers(1, n - 1, 2)):
                got = app.oneil_signal_at(fam, d, tf, int(t), o, h, l, c, v, rs, ch, rsf)
                assert got == bool(arr[t]), (fam, d, ch, rsf, t)
                if arr[t]:
                    checked.add((fam, d))
    assert len(checked) == 2 * len(app.ONEIL_PATTERN_FAMILIES), checked


@pytest.mark.parametrize("fam", ["cup_handle", "saucer", "cup_nohandle", "double_bottom"])
@pytest.mark.parametrize("short", [False, True])
def test_entry_signal_accepts_pattern_families(fam, short):
    d = "short" if short else "long"
    hit_any = False
    for seed in range(5):
        o, h, l, c, v, rs = _planted("1d", fam, seed, short)
        df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
        raw = app.oneil_pattern_signals(o, h, l, c, v, rs, "1d", chases=(None,), rs_filters=("none",))
        key = ("oneil_" + fam, "breakout", d, None, "none")
        hits = np.flatnonzero(raw.get(key, np.zeros(len(c), bool)))
        if not len(hits):
            continue
        t = int(hits[-1])
        res = app.oneil_entry_signal(df.iloc[:t + 1], "1d", "oneil_" + fam, d)
        assert res is not None and res["signal_pos"] == t
        assert (res["stop_hint"] < res["close"]) if d == "long" else (res["stop_hint"] > res["close"])
        hit_any = True
    assert hit_any


@pytest.mark.parametrize("tag", [
    "oneil_cup_handle__breakout__long__1d__atr3_chase10_h40_rsnone__v1",
    "oneil_cup_handle__breakout__short__1d__atr3_chase10_h40_rsqual1__v1",
    "oneil_saucer__breakout__long__1d__chase10_h20_pct8_rsnone__v1",
    "oneil_cup_nohandle__breakout__short__1d__atr2_chase5_h20_rsnone__v1",
    "oneil_double_bottom__breakout__long__1d__atr3_chase10_h20_rsnone_trl1__v1",
    "oneil_double_bottom__breakout__short__1d__chase10_h40_pct8_rsnone_tgt20__v1",
    "oneil_cup_handle__breakout__long__1w__atr3_chase10_h26_rsnone__v1",
    "oneil_double_bottom__breakout__short__1w__atr3_chase5_h12_rsnone__v1",
])
def test_replay_main_equals_research_and_simulate(tag):
    sp = rp.parse_tag(tag)
    tf = sp["tf"]
    total = 0
    for _tf, o, h, l, c, v, rs in _frames(tf):
        n = len(c)
        df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                          index=pd.date_range("2015-01-01", periods=n, freq="D"))
        rs_s = pd.Series(rs, index=df.index)
        a = rp.replay_symbol(df, rs_s, sp, 0.008, use_main=True, sig_cache={})
        b = rp.replay_symbol(df, rs_s, sp, 0.008, use_main=False, sig_cache={})
        assert a == b
        if a:  # research emits no key for a (family, dir) that never fires; run_specs cross-checks only then too
            assert rp._crosscheck(sp, "X", df, rs_s, 0.008, a) == []
        total += len(a)
    assert total > 0, tag


def test_family_grid_and_rows_shape():
    tags = rp.pattern_family_tags("cup", "1d,1w")
    assert len(tags) == len(set(tags)) == 1296
    for t in tags:
        assert rp.parse_tag(t)["family"] in app.ONEIL_PATTERN_FAMILIES
    assert rp.pattern_family_tags("double_bottom", "1w", "atr3")[0] == \
        "oneil_double_bottom__breakout__long__1w__atr3_chase5_h8_rsnone__v1"
    with pytest.raises(ValueError):
        rp.pattern_family_tags("flatbase", "1d")
    cell = rp.new_cell()
    rp.add_trades(cell, [dict(net=0.1, gross=0.108, held=5, reason="timeout", entry_bar=3),
                         dict(net=-0.05, gross=-0.042, held=2, reason="stop", entry_bar=9)])
    rows = rp.to_rows(rp.finalize({"t": cell}, "u"))
    m = rows[0]["metrics"]
    assert set(m) == {"n", "pfnet", "pfgross", "win_pct", "avg_held_bars", "pfnet_ex_top5", "top5_share",
                      "syms_traded", "universe", "exit_reasons"}
    assert m["exit_reasons"]["stop"] == {"n": 1, "avg_pct": -5.0}


def test_not_wired_live():
    src = (R / "main.py").read_text()
    for fam in app.ONEIL_PATTERN_FAMILIES:
        assert fam not in repr(getattr(app, "ONEIL_SWING_CELLS", ())), fam
    # the only callers of the pattern port are oneil_signal_at / oneil_entry_signal and the port itself
    assert src.count("oneil_pattern_signals(") == 2 and src.count("oneil_pattern_signal_array(") == 2
