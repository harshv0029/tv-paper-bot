"""B-873: interval=4h works in research scripts via scripts/research_interval.fetch_interval (1h fetch -> NSE-session 4h)."""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import research_interval as ri  # noqa: E402

SCRIPTS = ["elder_patterns_research", "elder_trend_context_research", "macd_divergence_research",
           "elder_macd_dirgap_research", "elder_indicators_research", "elder_batch3_research",
           "douglas_trade_mgmt_research", "elder_ge11_validate"]


def _hourly(days=3):
    rows = [pd.Timestamp(d.year, d.month, d.day, hh, 15) for d in pd.bdate_range("2026-01-05", periods=days)
            for hh in range(9, 16)]
    idx = pd.DatetimeIndex(rows).tz_localize("Asia/Kolkata")
    rng = np.random.default_rng(1)
    c = 100 + rng.normal(0, 1, len(idx)).cumsum()
    return pd.DataFrame({"Open": c - 0.2, "High": c + 1, "Low": c - 1, "Close": c,
                         "Volume": rng.integers(1, 100, len(idx)).astype(float)}, index=idx)


class FakeMain:
    def __init__(self, df):
        self.df, self.calls = df, []

    def fetch_ohlc(self, sym, period, interval):
        self.calls.append((period, interval))
        return self.df


def test_fetch_interval_4h_fetches_1h_and_resamples():
    h = _hourly()
    m = FakeMain(h)
    out = ri.fetch_interval(m, "X.NS", "5y", "4h")
    assert m.calls == [("730d", "1h")]  # period clamped, 1h fetched
    assert len(out) == 6
    day0 = h[h.index.date == h.index[0].date()]
    first4 = day0.iloc[:4]
    a = out.iloc[0]
    assert a["Open"] == first4["Open"].iloc[0] and a["Close"] == first4["Close"].iloc[-1]
    assert a["High"] == first4["High"].max() and a["Low"] == first4["Low"].min()
    assert a["Volume"] == first4["Volume"].sum()
    assert out["Volume"].sum() == h["Volume"].sum()
    assert {t.strftime("%H:%M") for t in out.index} == {"09:15", "13:15"}


def test_fetch_interval_passthrough_other_intervals():
    m = FakeMain(_hourly(1))
    assert ri.fetch_interval(m, "X.NS", "60d", "15m") is m.df
    assert m.calls == [("60d", "15m")]
    assert ri.fetch_interval(FakeMain(None), "X.NS", "", "4h") is None


def test_research_scripts_route_through_shared_path():
    for name in SCRIPTS:
        src = open(os.path.join(ROOT, "scripts", name + ".py")).read()
        assert "fetch_interval(" in src, name
        assert not re.search(r"m\.fetch_ohlc\(\w+, (args\.)?period, (args\.)?interval\)", src), name
