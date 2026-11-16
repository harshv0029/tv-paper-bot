"""B-1566: the fire-rate audit replays the LIVE entry functions over synthetic bars end to end (no network) and writes one
row per live cell, with fires only inside the live entry window."""
import importlib.util
import json
import os

import numpy as np
import pandas as pd

import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    spec = importlib.util.spec_from_file_location("fra", os.path.join(ROOT, "scripts", "fire_rate_audit_b1566.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _frame(interval, days):
    step = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}[interval]
    rows, d = [], pd.Timestamp("2026-10-01")
    while len({r.date() for r in rows}) < days:
        if d.weekday() < 5:
            if interval == "1d":
                rows.append(d + pd.Timedelta(hours=9, minutes=15))
            else:
                t = d + pd.Timedelta(hours=9, minutes=15)
                while t < d + pd.Timedelta(hours=15, minutes=30):
                    rows.append(t)
                    t += pd.Timedelta(minutes=step)
        d += pd.Timedelta(days=1)
    n = len(rows)
    rng = np.random.default_rng(7)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    c[-40::7] *= 0.94  # a few deep dips/spikes so band cells can trigger
    idx = pd.DatetimeIndex(rows).tz_localize("Asia/Kolkata")
    return pd.DataFrame({"Date": idx, "Open": c, "High": c * 1.004, "Low": c * 0.996, "Close": c,
                         "Volume": rng.integers(1000, 5000, n).astype(float)})


def test_audit_runs_on_live_functions_and_writes_rows(monkeypatch, tmp_path):
    m = _load()
    days = {"5m": 15, "15m": 30, "1h": 60, "1d": 400}
    monkeypatch.setattr(main, "fetch_ohlc", lambda sym, period, iv: _frame(iv, days[iv]))
    monkeypatch.setattr(main, "NSE_FULL_UNIVERSE", ["AAA.NS"])
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["AAA.NS"])
    out = tmp_path / "fra.json"
    monkeypatch.setattr(m, "OUT", str(out))
    monkeypatch.setattr(m, "BOT_URL", "")  # never call the live bot from a test (CI sets GITHUB_ACTIONS)
    m.main_run()
    d = json.load(open(out))
    tags = {r["tag"] for r in d["rows"]}
    assert set(main.CHAN_LONG_CELLS) <= tags and set(main.CHAN_SHORT_CELLS) <= tags
    assert set(main.MACDDIV_LONG_LIVE_CELLS) <= tags and set(main.BRK20_1H_LONG_CELLS) <= tags and "power_play" in tags
    assert d["errors"] == 0 and d["sessions"] == 5
    for r in d["rows"]:
        for _s, _day, bar in r["first"]:
            if "__5m__" in r["tag"] or "__15m__" in r["tag"]:
                hm = pd.Timestamp(bar).tz_convert("Asia/Kolkata")
                assert 9 * 60 + 15 <= hm.hour * 60 + hm.minute < 15 * 60


def test_live_counts_and_verdict(monkeypatch):
    m = _load()
    payload = {"day": "2026-11-16", "categories": {
        "buy": {"strategies": [{"strategy": "A", "scans": 5, "fired": 0, "blocked_triggers": 2, "attempts": 0}],
                "no_signal_strategies": [{"strategy": "B", "scans": 9}]},
        "swing": {"strategies": [{"strategy": "A", "scans": 7, "fired": 1, "blocked_triggers": 0, "attempts": 1}]}}}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return json.dumps(payload).encode()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: R())
    live = m.live_counts("https://bot.example")
    assert live["day"] == "2026-11-16" and live["tags"]["A"] == {"scans": 7, "fired": 1, "blocked_triggers": 2, "attempts": 1, "blocked_by_position": 0}
    assert live["tags"]["B"]["scans"] == 9 and live["tags"]["B"]["fired"] == 0
    monkeypatch.setattr(m, "SESSIONS", 1)
    assert m.verdict({"tag": "B", "symbol_session_fires": 3}, live, "2026-11-16") == "SUSPECT_WIRING"
    assert m.verdict({"tag": "A", "symbol_session_fires": 3}, live, "2026-11-16") == "ok"
    assert m.verdict({"tag": "C", "symbol_session_fires": 0}, live, "2026-11-16") == "ok"
    live["tags"]["B"]["blocked_by_position"] = 1  # B-1566: fired on a symbol another engine holds = not a wiring miss
    assert m.verdict({"tag": "B", "symbol_session_fires": 3}, live, "2026-11-16") == "ok"
    assert m.verdict({"tag": "B", "symbol_session_fires": 3}, live, "2026-11-13") == "n/a"  # different day: no verdict
    assert m.live_counts("") is None
