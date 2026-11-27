"""B-1746: the index fire audit replays the live ORB rule; zero index volume must block it, the no-volume twin must not."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import index_fire_audit as A  # noqa: E402
import main  # noqa: E402


def _bars(volume):
    rows = []
    for d, day in enumerate(("2026-10-05", "2026-10-06", "2026-10-07")):
        base = 100.0 + d * 2
        for i in range(75):
            t = pd.Timestamp(f"{day} 09:15") + pd.Timedelta(minutes=5 * i)
            c = base + (0.05 * i if i >= 6 else 0.0)  # flat opening range, then a steady climb above it
            rows.append({"Date": str(t), "Open": c - 0.02, "High": c + 0.03, "Low": c - 0.03, "Close": c,
                         "Volume": float(volume)})
    return pd.DataFrame(rows)


def test_zero_volume_blocks_live_orb_but_not_novol_twin():
    df = _bars(0)
    with_vol = A.live_orb(main, df, 30, 5, 50, "5m", True)
    no_vol = A.live_orb(main, df, 30, 5, 50, "5m", False)
    assert with_vol.sum() == 0
    assert no_vol.sum() >= 2  # day 2 and day 3 each break their opening range in an uptrend


def test_first_fire_per_day_only_and_per_day_counts():
    df = _bars(0)
    sig = A.live_orb(main, df, 30, 5, 50, "5m", False)
    days = A.per_day(df, sig, "2026-10-01", "2026-10-31")
    assert all(v <= 1 for v in days.values())
    assert set(days) == {"2026-10-05", "2026-10-06", "2026-10-07"}


def test_markdown_lists_every_cell():
    out = {"from": "a", "to": "b", "cells": {"^NSEI|5m": {"bars": 1, "orb|long": {"2026-10-06": 1}},
                                             "^BSESN|1h": {"error": "no data"}}}
    md = A.to_md(out)
    assert "| ^NSEI | 5m | orb | long | 1 | 1 |" in md and "no data" in md
    assert not np.isnan(1.0)
