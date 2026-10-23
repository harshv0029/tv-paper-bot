"""B-420: scripts/research_hold_summary.py - market-bar hold (not wall-clock) and the summary columns."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import research_hold_summary as hs  # noqa: E402


def test_held_bars_counts_bars_not_wall_clock():
    # two sessions: 3 bars on day 1, overnight gap of ~17.5h, then 3 bars on day 2
    day1 = [0, 300, 600]
    day2 = [600 + 63000 + k * 300 for k in range(3)]
    ts = day1 + day2
    assert hs.held_bars_from_ts(ts, ts[1], ts[4]) == 3  # wall-clock would be ~17.6h
    assert hs.held_bars_from_ts(ts, ts[0], ts[0]) == 0


def test_summarize_and_write(tmp_path):
    ts = [i * 300 for i in range(10)]
    trades = [
        {"entry_ts": ts[0], "exit_ts": ts[2], "net_pnl": 100.0, "gross_pnl": 120.0, "exit_reason": "target_hit"},
        {"entry_ts": ts[3], "exit_ts": ts[7], "net_pnl": -50.0, "gross_pnl": -30.0, "exit_reason": "stop_hit"},
    ]
    hs.attach_held_bars(trades, ts)
    r = hs.summarize("demo", trades, "full_universe (1/1 fetched)", run_id="123", bar_minutes=5)
    assert r["n"] == 2 and r["win_pct"] == 50.0
    assert r["pfnet"] == 2.0 and r["pfgross"] == 4.0
    assert r["avg_held_bars"] == 3.0 and r["avg_held_hrs"] == 0.25
    assert r["exit_reasons"] == {"target_hit": 1, "stop_hit": 1} and r["run_id"] == "123"
    hs.write_summary([r, hs.summarize("empty", [], "u", run_id="123")], str(tmp_path))
    rows = json.load(open(tmp_path / "summary.json"))
    assert rows[1]["n"] == 0 and rows[1]["avg_held_bars"] is None
    lines = open(tmp_path / "summary.tsv").read().splitlines()
    assert lines[0].split("\t") == list(hs.COLUMNS) and len(lines) == 3
