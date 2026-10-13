"""macddiv long 1h port parity with the research v_macd_divergence (pure signal function, not wired)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import macd_divergence_research as md  # noqa: E402
import main  # noqa: E402


def _bars(n=900, seed=5):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    h, l = c * 1.003, c * 0.997
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": 1e5}, index=idx)


def test_parity_with_research():
    df = _bars()
    for source in ("line", "hist"):
        ref = md.v_macd_divergence(df, 5, source, False)["long"]
        fired = 0
        for j in range(80, len(df)):
            sig = main.macd_divergence_long_entry_signal(df.iloc[:j + 1], source, 3.0, 5)
            # the port sees a trailing BRK20_CALC_WINDOW slice, so compare only where the window is the whole history
            if j + 1 <= main.BRK20_CALC_WINDOW:
                assert bool(sig) == bool(ref[j]), (source, j)
                fired += bool(sig)
            if sig:
                assert 0 < sig["stop_loss"] < sig["entry_price"]
        assert fired > 0
