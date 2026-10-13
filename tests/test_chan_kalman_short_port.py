"""B-913 port parity: main.py chan_kalman short functions equal the research implementation (scripts/)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import main  # noqa: E402
import chan_ext_research as cx  # noqa: E402
import chan_research as chn  # noqa: E402
import intraday_flatten_rerun as fl  # noqa: E402


def _frame(days=12, interval="15m", seed=3):
    rng = np.random.default_rng(seed)
    step = {"15m": 15, "5m": 5}[interval]
    idx = []
    for d in pd.bdate_range("2026-08-03", periods=days):
        t = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        idx += [t + pd.Timedelta(minutes=step * k) for k in range(int(375 / step))]
    n = len(idx)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.001, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e5}, index=pd.DatetimeIndex(idx))


def test_series_atr_masks_match_research():
    df = _frame()
    c = df["Close"].to_numpy(float)
    e1, s1 = main.chan_kalman_series(c, 1e-3)
    e2, s2 = cx.kalman_band(np.log(c), 1e-4, 1e-3)
    assert np.allclose(e1, e2) and np.allclose(s1, s2)
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    assert np.allclose(main.chan_atr14(h, l, c), chn.atr_arr(h, l, c), equal_nan=True)
    for a, b in zip(main.chan_flatten_masks(df.index, "15m"), fl.flatten_masks(df.index, "15m")):
        assert np.array_equal(a, b)


def test_short_trades_match_research_simulate():
    df = _frame()
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    atr = chn.atr_arr(h, l, c)
    cut, noentry, _ = fl.flatten_masks(df.index, "15m")
    err, sq = cx.kalman_band(np.log(c), 1e-4, 1e-3)
    sig = np.zeros(len(c)); sig[err > 1.0 * sq] = -1; sig[err < -1.0 * sq] = 1
    sig = np.where(noentry, 0, sig)
    ref = [t for t in chn.simulate(o, h, l, c, atr, sig, 4.0, 40, (err >= 0) | cut, (err <= 0) | cut) if t[0] == -1]
    ks = main.chan_kalman_series(c, 1e-3)
    masks = main.chan_flatten_masks(df.index, "15m")
    got, i, n = [], 0, len(c)
    while i < n - 2:
        sg = main.chan_kalman_band_short_entry_signal(df.iloc[:i + 1], "15m", 1.0, 1e-3, 4.0, ks=ks, masks=masks)
        if sg is None:
            i += 1
            continue
        e = i + 1
        ep = o[e]
        stop = ep + 4.0 * sg["atr"]
        x = None
        for j in range(e, min(n, e + 40)):
            r = main.chan_kalman_band_short_exit_reason(df.iloc[:j + 1], "15m", e, ep, stop, 40, 1e-3, ks=ks, masks=masks)
            if r:
                x = (j, r)
                break
        if x is None:
            j = min(n, e + 40) - 1
            x = (j, ("max_hold", c[j]))
        got.append((e, x[0], 1 - x[1][1] / ep))
        i = x[0] + 1
    assert len(ref) == len(got) and len(got) > 0
    for t, g in zip(ref, got):
        assert (t[1], t[2]) == (g[0], g[1]) and abs(t[3] - g[2]) < 1e-12
