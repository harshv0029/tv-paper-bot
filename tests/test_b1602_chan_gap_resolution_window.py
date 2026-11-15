"""chan_gap candle-size sweep driver (B-1020): tags, real-function calls, ranking, merge schema. Offline (synthetic)."""
import json
import os
import sys

import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_gap_tf_sweep as sw  # noqa: E402



def test_window_tag_is_distinct_and_grammar():
    a, b = sw.tag_for("long", "1h", 1.5), sw.tag_for("long", "1h", 1.5, 60)
    assert a != b and b == "chan_gap__buy_on_gap__long__1h__atr1d5_top10_w60d__v1"
    assert sw.tag_for("long", "1d", 4.0, 60).split("__")[3] == "1d"


def test_daily_as_intraday_one_bar_per_day_inside_cutoff():
    daily, intr = sw.synthetic_pair(1, "1d", n_days=150)
    assert len(intr) == len(daily)
    days = sw.split_days(intr, "1d", main.CHAN_FLATTEN_CUTOFF_MIN)
    assert len(days) == len(daily) and all(len(v) == 1 for v in days.values())


def test_1d_window_run_keeps_only_recent_days(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIRECTION", "long")
    monkeypatch.setenv("INTERVAL", "1d")
    monkeypatch.setenv("SYMBOL_LIMIT", "4")
    monkeypatch.setenv("WINDOW_DAYS", "60")
    sw.run()
    shard = json.load(open(tmp_path / "out" / "chan_gap_tf_long_1d_s0.json"))
    assert shard["window_days"] == 60
    start = (pd.Timestamp.now(tz="Asia/Kolkata").normalize() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    assert all(c["date"] >= start for c in shard["candidates"])
    for c in shard["candidates"]:
        assert all(t.endswith("_top10_w60d__v1") and "__1d__" in t for t in c["res"])
