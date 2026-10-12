"""Session-aware 1h->4h resample helper, and pfgross/median_stop emission by MCX sweep + combo_lab."""
import importlib.util
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from resample_4h import resample_1h_to_4h, BAR_HOURS_4H  # noqa: E402


def _hourly(days=2, tz="Asia/Kolkata"):
    rows = []
    for d in pd.bdate_range("2026-01-05", periods=days):
        for hh, mm in ((9, 15), (10, 15), (11, 15), (12, 15), (13, 15), (14, 15), (15, 15)):
            rows.append(pd.Timestamp(d.year, d.month, d.day, hh, mm))
    idx = pd.DatetimeIndex(rows)
    if tz:
        idx = idx.tz_localize(tz)
    n = len(idx)
    o = np.arange(n, dtype=float) + 100
    return pd.DataFrame({"Open": o, "High": o + 2, "Low": o - 1, "Close": o + 1, "Volume": 10.0}, index=idx)


def test_two_bars_per_day_session_anchored():
    out = resample_1h_to_4h(_hourly(2))
    assert len(out) == 4
    assert [t.strftime("%H:%M") for t in out.index] == ["09:15", "13:15", "09:15", "13:15"]


def test_ohlcv_aggregation():
    h = _hourly(1)
    out = resample_1h_to_4h(h)
    a, b = out.iloc[0], out.iloc[1]
    assert a["Open"] == h["Open"].iloc[0] and a["Close"] == h["Close"].iloc[3]
    assert a["High"] == h["High"].iloc[:4].max() and a["Low"] == h["Low"].iloc[:4].min() and a["Volume"] == 40
    assert b["Open"] == h["Open"].iloc[4] and b["Close"] == h["Close"].iloc[6] and b["Volume"] == 30


def test_never_spans_days_and_naive_index_ok():
    out = resample_1h_to_4h(_hourly(3, tz=None))
    assert len(out) == 6 and out.index.is_monotonic_increasing
    assert len({t.date() for t in out.index[:2]}) == 1


def test_empty_and_constant():
    assert len(resample_1h_to_4h(_hourly(1).iloc[0:0])) == 0
    assert BAR_HOURS_4H == 3.5


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mcx_stats_emits_pfgross_and_median_stop():
    m = _load("mcx_strategy_sweep")
    r = [0.05, -0.02, 0.03, -0.01]
    s = m.stats(r, [1, 2, 3, 4], cost=0.008, stops=[2.0, 4.0, 6.0])
    assert s["pfgross"] > s["pfnet"] and s["median_stop_pct"] == 4.0
    s2 = m.stats(r, [1, 2, 3, 4], cost=0.008, stops=[])
    assert s2["median_stop_pct"] is None
    assert m.stats([], [], 0.008) is None


def test_mcx_trade_records_stop_pct():
    m = _load("mcx_strategy_sweep")
    n = 40
    c = np.linspace(100, 110, n)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c})
    flag = pd.Series([False] * 20 + [True] * 5 + [False] * 15)
    m.atr = lambda d, n=14: pd.Series(np.full(len(d), 1.0))
    stops = []
    r, hr = m.trade(df, flag, 2.0, 1.0, stops=stops)
    assert len(r) == len(stops) == 1 and stops[0] > 0
    stops0 = []
    m.trade(df, flag, 0, 1.0, stops=stops0)
    assert stops0 == []


def test_combo_lab_summarize_has_pfgross():
    cl = _load("combo_lab")
    r = np.array([0.05, -0.02, 0.03, -0.01] * 100)
    m = cl.summarize(r, [2] * len(r), 0.008, [3.0] * 10)
    assert m["pfgross"] > m["pfnet"] and m["median_stop_pct"] == 3.0 and m["n"] == 400
