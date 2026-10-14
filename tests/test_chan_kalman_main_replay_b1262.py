"""B-1262: chan_kalman short main.py-replay harness covers 1h (port + converter + registry glob)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import main  # noqa: E402
import chan_kalman_main_to_docs as cv  # noqa: E402
import intraday_flatten_rerun as fl  # noqa: E402
import strategy_registry_chan_main as reg  # noqa: E402


def _frame_1h(days=40, seed=5):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-06-01", periods=days):
        t = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        idx += [t + pd.Timedelta(hours=k) for k in range(6)]
    n = len(idx)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.002, "Low": np.minimum(o, c) * 0.998, "Close": c, "Volume": 1e5},
                        index=pd.DatetimeIndex(idx))


def test_1h_masks_match_research_and_port_runs():
    df = _frame_1h()
    for a, b in zip(main.chan_flatten_masks(df.index, "1h"), fl.flatten_masks(df.index, "1h")):
        assert np.array_equal(a, b)
    ks = main.chan_kalman_series(df["Close"].to_numpy(float), 1e-3)
    masks = main.chan_flatten_masks(df.index, "1h")
    fired = 0
    for i in range(30, len(df)):
        sg = main.chan_kalman_band_short_entry_signal(df.iloc[:i + 1], "1h", 1.0, 1e-3, 2.5,
                                                      ks=(ks[0][:i + 1], ks[1][:i + 1]), masks=tuple(m[:i + 1] for m in masks[:2]) + (masks[2],))
        fired += sg is not None
    assert fired > 0


def test_converter_renames_band_to_band_mr_and_keeps_fields():
    res = {"groups": [{"family": "chan_kalman_main", "interval": "1h", "symbols": 5, "cost_round_trip": 0.008}],
           "results": {"t|": {"family": "chan_kalman_main", "interval": "1h", "n": 40, "win_pct": 55.0, "pfnet": 0.8, "pfgross": 1.4,
                              "avg_held_bars": 2.0, "avg_held_hrs": 2.0, "exit_reasons": {"flatten_1515": 40},
                              "tag": "chan_kalman__band__short__1h__atr2d5_hold40_ve1d0e4_z2d0_fl1515__v2"},
                       "x|": {"family": "pattern", "tag": "other"}}}
    out = cv.convert(res, "1")
    assert out["cost_round_trip_pct"] == 0.8 and len(out["rows"]) == 1
    r = out["rows"][0]
    assert "__band_mr__short__1h__" in r["tag"] and r["metrics"]["exit_reasons"] == {"flatten_1515": 40}
    assert r["metrics"]["avg_held_hours"] == 2.0


def test_registry_globs_run_files():
    assert "chan_kalman_main_replay_run_38390561217.json" in reg._RUNS
    assert all(not x.startswith("chan_kalman_long") for x in reg._RUNS)
    assert len(reg.build()) >= 0
