"""B-617: the Elder flag detector must be able to fire (it emitted 0 trades at every candle size before the fix)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import elder_patterns_research as epr  # noqa: E402


def _frame():
    # flat base, a sharp pole up, a 6-bar drift down (the flag), then a breakout bar
    c = [100.0] * 30 + list(np.linspace(100, 140, 10)) + [139, 138, 137, 136, 135, 134] + [150.0, 151.0]
    c = np.array(c)
    return pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": [1000] * len(c)})


def test_flag_fires_on_pole_drift_breakout():
    ent, _ = epr.d_flag(_frame(), k=6)
    assert bool(np.asarray(ent)[46])


def test_flag_silent_on_flat_series():
    c = np.full(60, 100.0)
    df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": [1000] * 60})
    ent, _ = epr.d_flag(df, k=6)
    assert not np.asarray(ent).any()
