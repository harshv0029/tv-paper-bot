"""B-568: the avg1 negative control must be a clean A/B against the atr3 cell (same entries, stops, exit bars)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import oneil_research as orx  # noqa: E402


def _series(n=200, seed=3):
    r = np.random.default_rng(seed)
    c = 100 + np.cumsum(r.normal(0, 1.2, n))
    o = np.r_[c[0], c[:-1]] + r.normal(0, 0.2, n)
    h = np.maximum(o, c) + abs(r.normal(0, 0.6, n))
    l = np.minimum(o, c) - abs(r.normal(0, 0.6, n))
    atr = np.full(n, 2.0)
    return o, h, l, c, atr


def test_avg_mode_has_same_entries_and_exit_bars_as_atr3():
    o, h, l, c, atr = _series()
    sig = np.zeros(len(c), bool)
    sig[5::7] = True
    for side in (1, -1):
        a = orx.simulate(sig, o, h, l, c, atr, 20, "atr", 3.0, side, 0.008, 3)
        b = orx.simulate(sig, o, h, l, c, atr, 20, "avg", 3.0, side, 0.008, 3)
        assert len(a) == len(b)
        assert [r[2] for r in a] == [r[2] for r in b]
        assert [r[3].split("+")[0] for r in a] == [r[3].split("+")[0] for r in b]
