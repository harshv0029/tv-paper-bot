"""chan_gap (Chan buy/short-on-gap) main.py port: parity with scripts/chan_research.py xs_rows gapz_* and day_returns."""
import os
import sys

import numpy as np
import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_research as cr  # noqa: E402


def _series(seed, n=300):
    rng = np.random.default_rng(seed)
    c = 500 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.02, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = np.full(n, 5e5)
    return o, h, l, c, v


def test_parity_with_research_rows():
    hits = 0
    for seed in range(12):
        o, h, l, c, v = _series(seed)
        dates = pd.bdate_range("2023-01-02", periods=len(c))
        atr = cr.atr_arr(h, l, c)
        res = cr.xs_rows(dates, o, h, l, c, v, atr)
        rows = res[0] if res else {}
        for mode, direction, side in (("gapz_long", "long", 1), ("gapz_short", "short", -1)):
            want = {}
            if mode in rows:
                for dt, sc in zip(rows[mode]["date"], rows[mode]["score"]):
                    want[str(dt)] = sc
            got = {}
            df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=dates)
            for i in range(120, len(c)):
                sig = main.chan_gap_entry_signal(df.iloc[:i], float(o[i]), direction, 2.5)
                if sig:
                    got[str(dates[i])] = sig["score"]
                    k = 2.5
                    stop = o[i] - side * k * atr[i - 1]
                    assert abs(sig["stop_loss"] - stop) < 1e-6
            want = {k_: v_ for k_, v_ in want.items() if k_ in {str(d) for d in dates[120:]}}
            assert set(got) == set(want), (seed, mode)
            for k_ in got:
                assert abs(got[k_] - want[k_]) < 1e-4
            hits += len(got)
    assert hits > 0


def test_select_top_and_exit():
    cands = {f"S{i}": {"score": (i - 5) / 100.0} for i in range(20)}
    assert main.chan_gap_select_top(cands, "long", 3) == ["S0", "S1", "S2"]
    assert main.chan_gap_select_top(cands, "short", 3) == ["S19", "S18", "S17"]
    bar = {"High": 105.0, "Low": 97.0, "Close": 101.0}
    assert main.chan_gap_exit_reason(bar, 100.0, 98.0, "long") == ("stop", 98.0)
    assert main.chan_gap_exit_reason(bar, 100.0, 96.0, "long") == ("close", 101.0)
    assert main.chan_gap_exit_reason(bar, 100.0, 105.0, "short") == ("stop", 105.0)
    assert main.chan_gap_exit_reason(bar, 100.0, 106.0, "short") == ("close", 101.0)


def test_rejects_short_history_and_always_returns_stop():
    o, h, l, c, v = _series(1, 50)
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
    assert main.chan_gap_entry_signal(df, 100.0, "long") is None
    assert main.chan_gap_entry_signal(df, 100.0, "bad") is None
