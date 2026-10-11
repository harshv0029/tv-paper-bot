import numpy as np
import pandas as pd

from scripts import minervini_sweep_lab as lab


def _df(closes):
    c = np.asarray(closes, float)
    return pd.DataFrame({"Open": c, "High": c * 1.001, "Low": c * 0.999, "Close": c, "Volume": 1e6})


def test_mult_tag():
    assert lab.mult_tag(1.5) == "1d5"
    assert lab.mult_tag(3.0) == "3"


def test_long_trail_stop_hit():
    df = _df([100] * 3 + [110] * 3 + [100] * 5)
    r = lab.simulate(df, 1, "long", 100, 90, 1.0, 2.0, 60, 0.008)
    assert r is not None and r[3] == "stop_or_trail" and r[1] == r[0] - 0.008


def test_short_max_hold_and_sign():
    df = _df([100] * 3 + [90] * 20)
    r = lab.simulate(df, 1, "short", 100, 120, 1.0, 4.0, 5, 0.0)
    assert r[3] == "max_hold" and r[0] > 0


def test_invalid_stop_rejected():
    df = _df([100] * 10)
    assert lab.simulate(df, 1, "long", 100, 105, 1.0, 2.0, 5, 0.0) is None


def test_summarize_fields():
    s = lab.summarize([0.1, -0.05], [0.09, -0.06], [3, 5], ["max_hold", "stop_or_trail"], 2680, 0.008)
    assert s["n"] == 2 and s["universe_size"] == 2680 and s["pfnet_gross"] > s["pfnet"]
    assert set(s["exits"]) == {"max_hold", "stop_or_trail"}
