import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import index_option_trigger_research as r  # noqa: E402


def _df(n=300, seed=1, intraday=False):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.003, np.minimum(o, c) * 0.997
    if intraday:
        d = [f"2026-01-{1 + i // 25:02d} {9 + (i % 25) // 4}:{(i % 4) * 15:02d}" for i in range(n)]
    else:
        d = pd.date_range("2020-01-01", periods=n, freq="B").astype(str)
    return pd.DataFrame({"Date": d, "Open": o, "High": h, "Low": l, "Close": c, "Volume": 0.0})


def test_nonvolume_triggers_fire_with_zero_volume_both_directions():
    df = _df(600)
    for trig in ("atr_range_break", "ema_cross", "rsi_thrust"):
        for d in ("long", "short"):
            assert len(r.simulate_signals(df, trig, d, 3.0, 30)) > 0, (trig, d)


def test_orb_intraday_fires_daily_does_not():
    assert r.trig_orb(_df(400, intraday=True)).sum() > 0
    assert r.trig_orb(_df(100)).sum() == 0


def test_no_lookahead_signal_prefix_stable():
    df = _df(300)
    for name, fn in r.NV_TRIGGERS.items():
        assert (fn(df)[:200] == fn(df.iloc[:200].reset_index(drop=True))).all(), name


def test_tag_grammar_and_distinct_directions():
    a = r.nv_tag("ema_cross", "long", "4h", 4.5)
    assert a == "ema__cross__long__4h__atr4d5_f9_s21__v1"
    assert a != r.nv_tag("ema_cross", "short", "4h", 4.5)


def test_resample_4h():
    d = _df(14)
    d["Date"] = [f"2026-01-0{1 + i // 7} {9 + i % 7}:15:00" for i in range(14)]
    o = r.resample_4h(d)
    assert len(o) == 4
    assert o.iloc[0]["Open"] == d.iloc[0]["Open"] and o.iloc[0]["Close"] == d.iloc[3]["Close"]
    assert o.iloc[0]["High"] == d.iloc[:4]["High"].max()


def test_run_synthetic_includes_nonvolume_cells():
    res = r.run("1d", ["^A"], [3.0], 30, 500, [0.8], 0.7, True)
    assert any(k.startswith("rsi__thrust__short__1d__") for k in res["cells"])
