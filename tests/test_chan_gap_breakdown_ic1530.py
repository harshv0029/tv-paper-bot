"""Chan_gap breakdown (user 2026-11-15): INTRADAY_CLOSE_1530=1 books each intraday candidate a second time at the 15:30
INTRADAY close (the 15:15 bar included), same entry, same price basis, so the exit-time effect is isolated."""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_gap_tf_sweep as sw  # noqa: E402


def test_ic_tag_grammar():
    t = sw.tag_for("short", "1h", 1.5, raw=True, ic=True)
    assert t == "chan_gap__short_on_gap__short__1h__atr1d5_top10_rawd_ic1530__v1"
    assert len(t.split("__")) == 6
    assert t != sw.tag_for("short", "1h", 1.5, raw=True, xd=True)


def test_ic_cutoff_keeps_the_1515_bar():
    ts = pd.date_range("2026-11-13 09:15", periods=7, freq="60min", tz="Asia/Kolkata")
    intr = pd.DataFrame({"Date": ts, "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": range(7)})
    live = sw.split_days(intr, "1h", 15 * 60 + 15)["2026-11-13"]
    ic = sw.split_days(intr, "1h", sw.IC_CUTOFF_MIN - 1 + sw.BAR_MIN["1h"])["2026-11-13"]
    assert len(live) == 6 and len(ic) == 7 and float(ic["Close"].iloc[-1]) == 6.0


def test_ic_twins_emitted_and_stops_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SYNTHETIC": "1", "DIRECTION": "short", "INTERVAL": "1h", "SYMBOL_LIMIT": "4",
                 "INTRADAY_CLOSE_1530": "1"}.items():
        monkeypatch.setenv(k, v)
    sw.run()
    cands = json.load(open(tmp_path / "out" / "chan_gap_tf_short_1h_s0.json"))["candidates"]
    twins = 0
    for c in cands:
        for tag, walk in c["res"].items():
            if tag.endswith("_ic1530__v1"):
                continue
            x = c["res"].get(tag.replace("__v1", "_ic1530__v1"))
            assert x is not None
            twins += 1
            if walk[0] == "stop":
                assert x == walk
    assert twins > 0


def test_ic_off_by_default_and_on_1d(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SYNTHETIC": "1", "DIRECTION": "short", "INTERVAL": "1d", "SYMBOL_LIMIT": "2",
                 "INTRADAY_CLOSE_1530": "1"}.items():
        monkeypatch.setenv(k, v)
    sw.run()
    cands = json.load(open(tmp_path / "out" / "chan_gap_tf_short_1d_s0.json"))["candidates"]
    assert not any(t.endswith("_ic1530__v1") for c in cands for t in c["res"])
