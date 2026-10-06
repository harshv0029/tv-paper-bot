"""Tests for main._dmi_arrays / dmi_scan / dmi_entry_signal (backlog B-11)."""
import numpy as np
import pandas as pd
import pytest

import main


def _walk(n=300, drift=0.0, vol=0.01, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 3, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 3, n)))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1000.0})


def _ref_dmi(h, l, c, period):
    """Independent plain-python Wilder reference (textbook recurrences)."""
    n = len(c)
    tr, pdm, mdm = [0.0] * n, [0.0] * n, [0.0] * n
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    def sm(x):
        out = [None] * n
        s = sum(x[:period]); out[period - 1] = s
        for i in range(period, n):
            s = s - s / period + x[i]; out[i] = s
        return out
    st, sp, sm_ = sm(tr), sm(pdm), sm(mdm)
    pdi = [None if st[i] is None else 100 * sp[i] / st[i] for i in range(n)]
    mdi = [None if st[i] is None else 100 * sm_[i] / st[i] for i in range(n)]
    dx = [None if pdi[i] is None else 100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) for i in range(n)]
    adx = [None] * n
    first = 2 * period - 2
    adx[first] = sum(dx[period - 1:first + 1]) / period
    for i in range(first + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return pdi, mdi, adx


def test_dmi_matches_independent_reference():
    d = _walk()
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    for per in (7, 14, 20):
        pdi, mdi, adx = main._dmi_arrays(h, l, c, per)
        rp, rm, ra = _ref_dmi(h, l, c, per)
        for i in range(2 * per, len(c)):
            assert pdi[i] == pytest.approx(rp[i]) and mdi[i] == pytest.approx(rm[i]) and adx[i] == pytest.approx(ra[i])


def test_uptrend_has_plus_di_dominant_and_high_adx_flat_has_low_adx():
    up = _walk(drift=0.004, vol=0.004)
    pdi, mdi, adx = main._dmi_arrays(up["High"].to_numpy(), up["Low"].to_numpy(), up["Close"].to_numpy(), 14)
    assert pdi[-1] > mdi[-1] and adx[-1] > 30
    flat = _walk(drift=0.0, vol=0.01, seed=11)
    flat["Close"] = 100 + np.sin(np.arange(300) / 3.0)  # pure oscillation, no trend
    flat["Open"], flat["High"], flat["Low"] = flat["Close"] - 0.1, flat["Close"] + 0.3, flat["Close"] - 0.3
    _, _, adx_f = main._dmi_arrays(flat["High"].to_numpy(), flat["Low"].to_numpy(), flat["Close"].to_numpy(), 14)
    assert adx_f[-1] < 25


def test_negation_swaps_plus_and_minus_di():
    d = _walk()
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    p1, m1, a1 = main._dmi_arrays(h, l, c, 14)
    p2, m2, a2 = main._dmi_arrays(-l, -h, -c, 14)
    assert np.allclose(p1[30:], m2[30:]) and np.allclose(m1[30:], p2[30:]) and np.allclose(a1[30:], a2[30:])


def test_cross_signals_are_real_crosses_and_long_short_are_disjoint_mirrors():
    d = _walk(n=600, vol=0.012, seed=5)
    rl = main.dmi_scan(d, "cross", "long")
    rs = main.dmi_scan(d, "cross", "short")
    assert rl["signal"].any() and rs["signal"].any()
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    pdi, mdi, _ = main._dmi_arrays(h, l, c, 14)
    for i in np.flatnonzero(rl["signal"]):
        assert pdi[i - 1] <= mdi[i - 1] and pdi[i] > mdi[i]
        assert rl["stop_loss"][i] < rl["entry_price"][i] < rl["target"][i]
    for i in np.flatnonzero(rs["signal"]):
        assert mdi[i - 1] <= pdi[i - 1] and mdi[i] > pdi[i]
        assert rs["target"][i] < rs["entry_price"][i] < rs["stop_loss"][i]
    assert not (rl["signal"] & rs["signal"]).any()


def test_adx_gate_is_subset_of_cross_and_requires_rising_adx_above_floor():
    d = _walk(n=800, vol=0.012, seed=9)
    cross = main.dmi_scan(d, "cross", "long")["signal"]
    gate = main.dmi_scan(d, "adx_gate", "long")["signal"]
    assert gate.sum() <= cross.sum() and not (gate & ~cross).any()
    _, _, adx = main._dmi_arrays(d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy(), 14)
    for i in np.flatnonzero(gate):
        assert adx[i] >= 20 and adx[i] > adx[i - 1]


def test_adx_turn_fires_when_adx_crosses_up_through_level():
    d = _walk(n=800, vol=0.012, seed=2)
    r = main.dmi_scan(d, "adx_turn", "long")
    pdi, mdi, adx = main._dmi_arrays(d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy(), 14)
    for i in np.flatnonzero(r["signal"]):
        assert adx[i - 1] <= 20 < adx[i] and pdi[i] > mdi[i]


def test_entry_signal_wrapper_and_validation():
    d = _walk(n=600, vol=0.012, seed=5)
    idx = int(np.flatnonzero(main.dmi_scan(d, "cross", "long")["signal"])[0])
    sig = main.dmi_entry_signal(d.iloc[:idx + 1], "cross", "long")
    assert sig is not None and sig["stop_loss"] < sig["entry_price"] < sig["target"]
    with pytest.raises(ValueError):
        main.dmi_scan(d, "nope", "long")
    with pytest.raises(ValueError):
        main.dmi_scan(d, "cross", "up")
    assert main.dmi_entry_signal(d.iloc[:2], "cross", "long") is None
