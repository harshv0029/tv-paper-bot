import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import intraday_flatten_rerun as fr  # noqa: E402
import chan_research as chn  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_pattern_lab_env():
    """pattern_lab reads env TF at import; do not leak a 15m import into other test modules."""
    had_mod = "pattern_lab" in sys.modules
    old_tf = os.environ.get("TF")
    yield
    if not had_mod:
        sys.modules.pop("pattern_lab", None)
    if old_tf is None:
        os.environ.pop("TF", None)
    else:
        os.environ["TF"] = old_tf


def _idx(interval, days=3, tz="Asia/Kolkata"):
    bm = fr.BAR_MIN[interval]
    out = []
    for d in pd.bdate_range("2026-09-01", periods=days):
        t = d + pd.Timedelta(hours=9, minutes=15)
        while t < d + pd.Timedelta(hours=15, minutes=30):
            out.append(t)
            t += pd.Timedelta(minutes=bm)
    idx = pd.DatetimeIndex(out)
    return idx.tz_localize(tz) if tz else idx


def test_cut_bar_is_last_bar_ending_by_1515():
    for itv, hh, mm in (("5m", 15, 10), ("15m", 15, 0), ("1h", 14, 15)):
        idx = _idx(itv)
        cut, _, _ = fr.flatten_masks(idx, itv)
        assert cut.sum() == 3  # one per day
        loc = idx[cut]
        assert all((t.hour, t.minute) == (hh, mm) for t in loc)
        # its end time is at/before 15:15, and the next bar's end is after
        assert loc[0].hour * 60 + loc[0].minute + fr.BAR_MIN[itv] <= fr.CUTOFF_MIN


def test_noentry_blocks_entries_that_would_fill_on_or_after_cut_and_last_bar():
    idx = _idx("15m")
    cut, noentry, dci = fr.flatten_masks(idx, "15m")
    ci = np.flatnonzero(cut)[0]
    assert not noentry[ci - 2] and noentry[ci - 1] and noentry[ci] and noentry[ci + 1]
    # last bar of every day cannot signal (would carry overnight)
    last = np.r_[idx.date[1:] != idx.date[:-1], True]
    assert noentry[last].all()
    assert not noentry[0]
    assert (dci[:ci + 2] == ci).all()


def test_naive_index_treated_as_ist_and_utc_converted():
    idx_naive = _idx("15m", tz=None)
    c1, _, _ = fr.flatten_masks(idx_naive, "15m")
    idx_utc = _idx("15m").tz_convert("UTC")
    c2, _, _ = fr.flatten_masks(idx_utc, "15m")
    assert (c1 == c2).all()


def test_flat_tag_roundtrip_and_new_version():
    old = "chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0__v1"
    new = fr.flat_tag(old)
    assert new.endswith("_fl1515__v2") and old != new
    assert fr.source_tag(new) == old
    assert fr.source_tag(old) is None


def test_simulate_flat_matches_pattern_lab_when_cut_never_binds():
    os.environ["TF"] = "15m"
    import pattern_lab as pl
    rng = np.random.default_rng(3)
    n = 400
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.002
    l = np.minimum(o, c) * 0.998
    atr = pl.atr_arr(h, l, c)
    sig = np.zeros(n, bool)
    sig[20::37] = True
    for side in (1, -1):
        for k in (0, 2.5):
            r_ref, held_ref = pl.simulate(sig, o, h, l, c, atr, 10, k, 0.008, side)
            nets, _, held, _ = fr.simulate_flat(sig, o, h, l, c, atr, 10, k, 0.008, side,
                                                np.zeros(n, bool), np.full(n, n - 1))
            # reference drops trades lacking a full `hold` of future bars; flat version keeps those clamped to the final bar
            assert np.allclose(nets[:len(r_ref)], r_ref) and held[:len(held_ref)] == held_ref


def test_simulate_flat_exits_at_cut_and_never_overnight():
    idx = _idx("15m", days=3)
    n = len(idx)
    c = np.full(n, 100.0)
    o, h, l = c.copy(), c * 1.001, c * 0.999
    atr = np.full(n, 0.5)
    cut, noentry, dci = fr.flatten_masks(idx, "15m")
    sig = np.zeros(n, bool)
    sig[3] = True
    nets, gross, held, why = fr.simulate_flat(sig, o, h, l, c, atr, 25, 0, 0.0, -1, noentry, dci)
    ci = int(dci[0])
    assert len(nets) == 1 and why == ["flatten_1515"] and held == [ci - 4 + 1]
    # a signal too close to the cut is dropped entirely
    sig2 = np.zeros(n, bool)
    sig2[ci - 1] = True
    assert fr.simulate_flat(sig2, o, h, l, c, atr, 25, 0, 0.0, 1, noentry, dci)[0] == []
    # a stop before the cut still wins
    l2 = l.copy()
    l2[10] = 90.0
    nets, _, _, why = fr.simulate_flat(np.eye(1, n, 3, dtype=bool)[0], o, h, l2, c, atr, 25, 2.0, 0.0, 1, noentry, dci)
    assert why == ["stop"]


def test_chan_simulate_with_flatten_masks_closes_before_cut_day_end():
    idx = _idx("15m", days=2)
    n = len(idx)
    rng = np.random.default_rng(5)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    atr = chn.atr_arr(h, l, c)
    atr[:] = np.where(np.isnan(atr), 0.3, atr)
    cut, noentry, dci = fr.flatten_masks(idx, "15m")
    sig = np.where(noentry, 0, np.where(np.arange(n) % 5 == 0, 1, 0))
    tr = chn.simulate(o, h, l, c, atr, sig, 2.5, 40, cut, cut)
    assert tr
    for side, e, x, g, why in tr:
        assert dci[e] == dci[x] and x <= dci[e]  # same session, never past the cut bar


def test_target_cells_derived_from_registry_and_floor():
    cells = fr.target_cells()
    assert cells, "expected viable intraday-bar cells in the registry"
    import strategy_registry as sr
    for d in cells:
        assert d.metrics.pfnet >= sr.PFNET_LIVE_FLOOR and d.timeframe in fr.BAR_MIN
        assert d.metrics.avg_held_hrs <= fr.SESSION_HOURS
    assert len(fr.target_cells(floor=99)) == 0


def _fake_frames(interval, ndays=30):
    idx = _idx(interval, days=ndays)
    rng = np.random.default_rng(11)

    def frames(syms, itv):
        for _ in syms:
            c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(idx))))
            o = np.r_[c[0], c[:-1]]
            yield 0, pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.002, "Low": np.minimum(o, c) * 0.998,
                                   "Close": c, "Volume": np.full(len(idx), 1e6)}, index=idx)
    return frames


def test_end_to_end_chan_and_pattern_then_merge(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    monkeypatch.setenv("INTERVAL", "15m")
    monkeypatch.setenv("MAXSYM", "3")
    monkeypatch.setattr(fr, "_frames", _fake_frames("15m"))
    for fam in ("chan_kalman", "pattern"):
        monkeypatch.setenv("FAMILY", fam)
        monkeypatch.setenv("UNI", "full")
        fr.run()
    files = sorted(str(p) for p in tmp_path.glob("flat_*.json"))
    assert len(files) == 2
    res = fr.merge(files, out=str(tmp_path / "res.json"))
    assert res and all(k.split("|")[0].endswith("__v2") for k in res)
    for r in res.values():
        assert r["interval"] == "15m" and r["avg_held_hrs"] <= fr.SESSION_HOURS + 1e-9  # flat: never past one session
        assert set(r["exit_reasons"]) <= {"stop", "flatten_1515", "max_hold", "state_exit"}
    assert any("flatten_1515" in r["exit_reasons"] for r in res.values())
    assert json.load(open(tmp_path / "res.json"))["results"]
