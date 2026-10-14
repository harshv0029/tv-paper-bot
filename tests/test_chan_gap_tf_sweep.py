"""chan_gap candle-size sweep driver (B-1020): tags, real-function calls, ranking, merge schema. Offline (synthetic)."""
import json
import os
import sys

import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_gap_tf_sweep as sw  # noqa: E402


def test_tags_follow_grammar_and_are_distinct():
    tags = {sw.tag_for(d, tf, a) for d in ("long", "short") for tf in ("5m", "15m", "1h") for a in sw.DEFAULT_ATRS}
    assert len(tags) == 18
    assert sw.tag_for("short", "15m", 1.5) == "chan_gap__short_on_gap__short__15m__atr1d5_top10__v1"
    assert sw.tag_for("long", "1h", 4.0) == "chan_gap__buy_on_gap__long__1h__atr4d0_top10__v1"
    for t in tags:
        assert t == t.lower() and all(c.isalnum() or c == "_" for c in t)


def test_walk_uses_real_exit_stop_and_close():
    bars = pd.DataFrame({"Open": [100, 101], "High": [101, 106], "Low": [99, 100], "Close": [101, 105]})
    assert sw.day_walk(main, bars, 100.0, 105.5, "short", "15m") == ("stop", 105.5)
    assert sw.day_walk(main, bars, 100.0, 120.0, "short", "15m") == ("close", 105.0)
    assert sw.day_walk(main, bars, 100.0, 98.0, "long", "15m") == ("close", 105.0)


def test_split_days_drops_bars_past_cutoff():
    t = pd.date_range("2026-01-05 09:15", periods=30, freq="15min", tz="Asia/Kolkata")
    df = pd.DataFrame({"Date": t, "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0})
    day = sw.split_days(df, "15m", main.CHAN_FLATTEN_CUTOFF_MIN)["2026-01-05"]
    end = pd.to_datetime(day["Date"]).iloc[-1]
    assert end.hour * 60 + end.minute + 15 <= main.CHAN_FLATTEN_CUTOFF_MIN


def test_synthetic_run_and_merge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    for d in ("long", "short"):
        monkeypatch.setenv("DIRECTION", d)
        monkeypatch.setenv("INTERVAL", "1h")
        monkeypatch.setenv("SYMBOL_LIMIT", "6")
        sw.run()
    out = sw.merge(str(tmp_path / "out"), str(tmp_path / "r.json"))
    r = json.load(open(tmp_path / "r.json"))
    assert r["synthetic"] is True and r["cost_round_trip_pct"] == main.ROUND_TRIP_COST_PCT
    for row in out["rows"]:
        assert row["tag"].startswith("chan_gap__") and "__1h__" in row["tag"]
        assert {"n", "pfnet", "win_pct", "avg_held_hours", "exit_reasons"} <= set(row["metrics"])
