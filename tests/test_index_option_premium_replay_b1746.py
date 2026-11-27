"""B-1746 step 3: premium-proxy replay helpers (research script, no live logic)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import index_option_premium_replay as X  # noqa: E402


def test_days_to_expiry_weekly_tuesday_and_monthly():
    # Mon 2026-11-23 09:15 -> Tue 2026-11-24 15:30 = 1 day 6h15m
    d = X.days_to_expiry(pd.Timestamp("2026-11-23 09:15"), 1, True)
    assert abs(d - (1 + 6.25 / 24)) < 1e-6
    # expiry day after the close rolls to next week
    assert X.days_to_expiry(pd.Timestamp("2026-11-24 15:45"), 1, True) > 6
    # monthly last Tuesday of Nov 2026 = 24th
    assert abs(X.days_to_expiry(pd.Timestamp("2026-11-24 09:15"), 1, False) - 6.25 / 24) < 1e-6


def test_replay_is_intraday_only_and_one_position_at_a_time():
    df = X.synthetic_intraday("^NSEI", days=3)
    X.UNDERLYING_ROW["NIFTY"] = (50, 1, True)
    sig = np.ones(len(df), bool)
    tr = X.replay(df, sig, "call", "NIFTY", "5m", (10.0, 5.0, 5.0), 375, 0.13, 65)
    assert tr
    hhmm = df["Date"].str[11:16].tolist()
    for t in tr:
        assert t["entry"] <= X.LAST_ENTRY
    # every trade ends on its own entry day, never past the square-off
    pos = {d: [i for i, x in enumerate(df["Date"].str[:10]) if x == d] for d in set(df["Date"].str[:10])}
    for t in tr:
        idx = pos[t["day"]][0] + hhmm[pos[t["day"]][0]:].index(t["entry"])
        assert hhmm[idx + t["hold_bars"]] <= X.SQUARE_OFF
        assert df["Date"].iloc[idx + t["hold_bars"]][:10] == t["day"]


def test_stats_and_viable_screen():
    tr = [{"ret": 0.2, "hold_bars": 3, "exit": "stop", "net_inr_proxy": 100.0},
          {"ret": -0.1, "hold_bars": 2, "exit": "stop", "net_inr_proxy": -60.0}]
    s = X.stats(tr, 2)
    assert s["n"] == 2 and s["pfnet_08"] == round(0.192 / 0.108, 3)
    assert not X.viable({"is": s, "oos": s})  # fewer than 5 trades per side
