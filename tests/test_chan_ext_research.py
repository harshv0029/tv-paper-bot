import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import chan_ext_research as cx  # noqa: E402

GRAMMAR = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*__[a-z0-9_]+?__(long|short)__(1d|1h|15m|5m)__[a-z0-9_]+__v1$")


def _walk(n=600, seed=1, phi=1.0):
    rng = np.random.default_rng(seed)
    y = np.zeros(n)
    for i in range(1, n):
        y[i] = phi * y[i - 1] + rng.normal(0, 0.01)
    return 100 * np.exp(y)


def test_adf_separates_stationary_from_random_walk():
    stat = np.log(_walk(phi=0.8))
    rw = np.log(_walk(phi=1.0, seed=4))
    assert cx.adf_t(stat) < -2.871 < cx.adf_t(rw[:120]) + 5  # stationary clears the 5% critical value
    assert cx.adf_t(stat) < cx.adf_t(rw)


def test_hurst_and_variance_ratio_directions():
    mr = np.log(_walk(n=400, phi=0.7))
    assert cx.hurst(mr) < 0.5
    assert cx.var_ratio(mr) < 1.0


def test_kalman_band_tracks_and_flags_shock():
    y = np.log(np.r_[np.full(100, 100.0), 90.0, np.full(10, 100.0)])
    err, sq = cx.kalman_band(y, 1e-4, 1e-4)
    assert err[100] < -2 * sq[100]  # a one-bar drop is far outside the band
    assert abs(err[50]) < 1e-9


def test_cells_have_both_directions_stop_and_grammar():
    c = _walk(n=600, phi=0.9)
    v = np.full(600, 1e5)
    rng = np.random.default_rng(2)
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.004, np.minimum(o, c) * 0.996
    atr = cx.chn.atr_arr(h, l, c)
    n_cells = 0
    for gen in (cx.kalman_cells(c, "1d"), cx.vwma_cells(c, v, "1d"), cx.mr_gate_cells(c, "1d")):
        for fam, var, params, sig, hold, xl, xs in gen:
            n_cells += 1
            assert len(sig) == 600 and set(np.unique(sig)) <= {-1.0, 0.0, 1.0}
            for k in cx.KS:
                tr = cx.chn.simulate(o, h, l, c, atr, sig, k, hold, xl, xs)
                for side, nm in ((1, "long"), (-1, "short")):
                    assert GRAMMAR.match(cx.tag(fam, var, nm, "1d", {**params, "atr": cx.kf(k)}))
                assert all(t[4] in ("stop", "state_exit", "max_hold") for t in tr)
    assert n_cells == 4 + 4 + 7


def test_intraday_wrap_flat_at_day_end():
    idx = pd.date_range("2026-01-05 09:15", periods=8, freq="5min").append(pd.date_range("2026-01-06 09:15", periods=8, freq="5min"))
    df = pd.DataFrame({"Close": np.arange(16.0)}, index=idx)
    last = cx.day_flags(df)
    assert last.sum() == 2 and last[7] and last[15]
    sig, xl, xs = cx.intraday_wrap(np.ones(16), None, None, last)
    assert sig[7] == 0 and xl[7] and xs[15]


def test_lateday_continuation_long_and_short():
    def day(date, base, drift):
        idx = pd.date_range(f"{date} 09:15", periods=25, freq="15min", tz="Asia/Kolkata")  # 09:15 .. 15:15
        c = np.linspace(base, base + drift, 25)
        return pd.DataFrame({"Open": c - 0.01, "High": c + 0.02, "Low": c - 0.02, "Close": c, "Volume": 1e5}, index=idx)
    d1 = day("2026-01-05", 100, 0)
    d2 = day("2026-01-06", 100, 3.0)  # +3% by the close; ret to 15:00 > 2%
    rows = cx.lateday_trades(pd.concat([d1, d2]), (2.5,), 0.0, "15m", (0.02,))
    longs = [t for t in rows if "__long__" in t]
    assert longs and all(GRAMMAR.match(t) for t in rows)
    d3 = day("2026-01-07", 103, -4.0)
    rows2 = cx.lateday_trades(pd.concat([d1, d2, d3]), (2.5,), 0.0, "15m", (0.02,))
    assert any("__short__" in t for t in rows2)


def test_xs_cells_decile_and_crash_gate():
    rows = []
    for i in range(300):
        ret = i / 300.0
        gl = 0.05 if i >= 270 else 0.0
        gs = 0.04 if i < 30 else 0.0
        rows.append(["20260105", ret, -0.02 if i % 2 else -0.12, {"2d5": [gl, gs, 25, "max_hold", "max_hold"]}])
    cells = cx.xs_cells(rows, 0.008)
    keys = list(cells)
    assert any("__long__" in k and "crashnone" in k for k in keys) and any("__short__" in k and "crashcr10" in k for k in keys)
    ln = [v for k, v in cells.items() if "__long__" in k and "crashnone" in k][0]
    lc = [v for k, v in cells.items() if "__long__" in k and "crashcr10" in k][0]
    assert ln["n"] == 30 and lc["n"] < ln["n"]  # crash gate removes the rebalances inside the drawdown


def test_hygiene_row_counts_glitches():
    ix = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame({"Open": [10, 10, 10, 10, 10.0], "High": [11, 11, 11, 11, 11.0], "Low": [9, 9, 9, 9, 9.0],
                       "Close": [10, 10, 20, 10, 10.0], "Volume": [1, 0, 1, 1, 1]}, index=ix)
    r = cx.hygiene_row(df)
    assert r["bad_ohlc"] == 1 and r["jump_gt35"] == 2 and r["zero_vol"] == 1
