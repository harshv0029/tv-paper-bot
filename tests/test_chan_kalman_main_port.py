"""B-1467 port parity: main.py chan_kalman v1 band functions (UNWIRED) equal the research harness
(scripts/chan_ext_research.py kalman_cells / intraday_wrap / day_flags + scripts/chan_research.py simulate), and the
main-calling replay walk (scripts/chan_kalman_main_replay_job.py) reproduces research simulate trade-for-trade."""
import inspect
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import main  # noqa: E402
import chan_ext_research as cx  # noqa: E402
import chan_research as chn  # noqa: E402
import chan_kalman_main_replay_job as job  # noqa: E402


def _frame(interval, seed, vol=0.012):
    rng = np.random.default_rng(seed)
    step = {"5m": 5, "15m": 15, "1h": 60}.get(interval)
    if step:
        idx = []
        for d in pd.bdate_range("2026-08-03", periods=15):
            t = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
            idx += [t + pd.Timedelta(minutes=step * k) for k in range(int(375 / step))]
    else:
        idx = list(pd.bdate_range("2022-01-03", periods=700))
    n = len(idx)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, vol / 3, n))  # gaps, so the gap-aware stop path is exercised
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e5}, index=pd.DatetimeIndex(idx))


def _research_cells(df, interval):
    """{(ve, z): (sig, xl, xs)} exactly as chan_ext_research.run builds them."""
    c = df["Close"].to_numpy(float)
    last = cx.day_flags(df) if interval in cx.INTRADAY else None
    out = {}
    for _fam, _var, params, sig, _hold, xl, xs in cx.kalman_cells(c, interval):
        if last is not None:
            sig, xl, xs = cx.intraday_wrap(sig, xl, xs, last)
        ve = {"1d0e4": 1e-4, "10d0e4": 1e-3}[params["ve"]]
        out[(ve, float(params["z"].replace("d", ".")))] = (sig, xl, xs)
    return out


CASES = [("5m", 1), ("15m", 2), ("1h", 6), ("1d", 4), ("1d", 5)]


@pytest.mark.parametrize("interval,seed", CASES)
def test_precompute_matches_research_arrays(interval, seed):
    df = _frame(interval, seed)
    ref = _research_cells(df, interval)
    assert len(ref) == 4
    for (ve, z), (sig, xl, xs) in ref.items():
        pre = main.chan_kalman_band_v1_precompute(df, interval, z, ve)
        assert np.array_equal(pre["sig"], sig)
        assert np.array_equal(pre["exit_long"], np.asarray(xl, bool))
        assert np.array_equal(pre["exit_short"], np.asarray(xs, bool))
        h, l, c = (df[x].to_numpy(float) for x in ("High", "Low", "Close"))
        assert np.allclose(pre["atr"], chn.atr_arr(h, l, c), equal_nan=True)
    if interval in cx.INTRADAY:
        assert np.array_equal(main.chan_kalman_v1_day_last(df.index), cx.day_flags(df))


def _norm(trades):
    return [(s, e, xi, round(g, 12), {"data_end": "max_hold", "eod_flat": "state_exit"}.get(r, r)) for s, _i, e, xi, g, r in trades]


@pytest.mark.parametrize("interval,seed", CASES)
def test_combined_walk_equals_research_simulate(interval, seed):
    df = _frame(interval, seed)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    atr = chn.atr_arr(h, l, c)
    total, reasons = 0, set()
    for (ve, z), (sig, xl, xs) in _research_cells(df, interval).items():
        pre = main.chan_kalman_band_v1_precompute(df, interval, z, ve)
        for k in chn.KS:
            ref = [(s, e, xi, round(g, 12), r) for s, e, xi, g, r in chn.simulate(o, h, l, c, atr, sig, k, 40, xl, xs)]
            got = _norm(job.walk(main, df, interval, pre, k, (1, -1)))
            assert got == ref, (interval, ve, z, k)
            total += len(ref)
            reasons |= {t[4] for t in ref}
    assert total > 20
    assert "stop" in reasons and "state_exit" in reasons


@pytest.mark.parametrize("interval,seed", CASES)
def test_per_direction_walk_equals_research_one_side(interval, seed):
    df = _frame(interval, seed)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    atr = chn.atr_arr(h, l, c)
    for (ve, z), (sig, xl, xs) in _research_cells(df, interval).items():
        pre = main.chan_kalman_band_v1_precompute(df, interval, z, ve)
        for side in (1, -1):
            s1 = np.where(sig == side, sig, 0)
            for k in chn.KS:
                ref = [(s, e, xi, round(g, 12), r) for s, e, xi, g, r in chn.simulate(o, h, l, c, atr, s1, k, 40, xl, xs)]
                assert _norm(job.walk(main, df, interval, pre, k, (side,))) == ref


def test_last_bar_entry_on_sliced_frame_equals_precomputed():
    df = _frame("1d", 7)
    pre = main.chan_kalman_band_v1_precompute(df, "1d", 1.0, 1e-3)
    hits = 0
    for i in range(30, len(df)):
        for d in ("long", "short"):
            a = main.chan_kalman_band_v1_entry_signal(df.iloc[:i + 1], "1d", d, z=1.0, ve=1e-3, atr_mult=2.5)
            b = main.chan_kalman_band_v1_entry_signal(df, "1d", d, z=1.0, ve=1e-3, atr_mult=2.5, pos=i, pre=pre)
            assert a == b
            hits += a is not None
    assert hits > 5


def test_stop_always_set_or_no_entry():
    assert main.chan_kalman_band_v1_stop(100.0, 2.0, 1.5, "long") == 97.0
    assert main.chan_kalman_band_v1_stop(100.0, 2.0, 1.5, "short") == 103.0
    for bad in ((0, 2.0, 1.5), (100.0, 0, 1.5), (100.0, 2.0, 0), (100.0, -1, 1.5)):
        assert main.chan_kalman_band_v1_stop(*bad, "long") is None
    df = _frame("1d", 4)
    assert main.chan_kalman_band_v1_entry_signal(df, "1d", "long", atr_mult=0) is None
    assert main.chan_kalman_band_v1_entry_signal(df, "1d", "sideways") is None


def test_eod_flat_reason_on_intraday_last_bar():
    df = _frame("5m", 1)
    pre = main.chan_kalman_band_v1_precompute(df, "5m", 2.0, 1e-3)
    last = np.flatnonzero(pre["last"])
    j = int(last[0])
    bars = {k: df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")}
    pre2 = dict(pre, err=np.full(len(df), -1.0))  # long still below the mean at the day's last bar
    r = main.chan_kalman_band_v1_exit_reason(bars, "long", j - 1, 1e-9, 40, pos=j, pre=pre2)
    assert r == ("eod_flat", float(bars["Close"][j]))


def test_tags_match_registry_grammar():
    import strategy_registry as sr
    names = {s.name for s in sr.REGISTRY}
    src = job.make_tag("band", "long", "5m", 4.0, 1e-3, 1.0)
    assert src == "chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0__v1" and src in names
    assert job.make_tag("band", "short", "15m", 1.5, 1e-4, 2.0) == chn.tag(
        "chan_kalman", "band", "short", "15m", {"hold": 40, "ve": "1d0e4", "z": "2d0", "atr": "1d5"})
    assert job.make_tag("band_srcmain", "long", "1d", 2.5, 1e-3, 2.0).startswith("chan_kalman__band_srcmain__long__1d__")


def test_port_is_unwired():
    tags = set(main._STRATEGY_TAG_TO_REGISTRY_NAME) | set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    # the v2 fl1515 tags (a different, already-wired family) are allowed; no v1 band / srcmain tag may be mapped
    assert not any("band_srcmain" in t or (t.startswith("chan_kalman__band__") and t.endswith("__v1")) for t in tags)
    src = inspect.getsource(main)
    for fn in ("chan_kalman_band_v1_entry_signal", "chan_kalman_band_v1_exit_reason", "chan_kalman_band_v1_precompute"):
        # only the definition (and calls inside the port block itself) may mention it
        uses = [ln for ln in src.splitlines() if fn + "(" in ln and not ln.lstrip().startswith("def ")]
        assert all("pre = chan_kalman_band_v1_precompute(df, interval, z, ve)" in ln for ln in uses), uses


def test_replay_job_synthetic_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("SYMBOL_LIMIT", "2")
    monkeypatch.setenv("TF", "15m")
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    path = job.main_()
    import json
    d = json.load(open(path))
    assert d["synthetic"] is True and d["symbols_kept"] == 2 and len(d["rows"]) == 48
    r = d["rows"][0]
    for k in ("n", "pfnet", "pfgross", "win_pct", "avg_held_bars", "avg_held_hours", "exit_reasons", "is", "oos"):
        assert k in r["metrics"]
    assert sum(x["metrics"]["n"] for x in d["rows"]) > 0
    with pytest.raises(SystemExit):
        job.parse_job("4h")
    assert job.parse_job("5m_s1of2") == ("5m", 1, 2)
