"""Dispatch-readiness tests for B-786 (O'Neil / Kalman replay inputs), B-112 (lunar sweep), B-541 (rolling monitor)."""
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
import yaml

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import lunar_sweep as L  # noqa: E402
import oneil_research as orx  # noqa: E402

WF = R / ".github" / "workflows"


def _wf(name):
    d = yaml.safe_load((WF / name).read_text())
    d["on"] = d.get("on", d.get(True))
    return d


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


# ---------------------------------------------------------------- B-112 moon phase
def test_moon_phase_matches_published_2024_events():
    ev = {k + t.strftime("%Y-%m-%d"): t for k, t in L.phase_events(utc(2024, 1, 1), utc(2024, 2, 10))}
    expect = (("new2024-01-11", 11, 57), ("full2024-01-25", 17, 54),
              ("first_quarter2024-01-18", 3, 53), ("last_quarter2024-02-02", 23, 18))
    for key, hh, mm in expect:
        t = ev[key]
        ref = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
        assert abs((t - ref).total_seconds()) < 3600


def test_moon_phase_is_deterministic_and_alternates():
    a = L.phase_events(utc(2021, 1, 1), utc(2021, 12, 31))
    assert a == L.phase_events(utc(2021, 1, 1), utc(2021, 12, 31))
    kinds = [k for k, _ in a]
    order = ["new", "first_quarter", "full", "last_quarter"]
    i = order.index(kinds[0])
    assert kinds == [order[(i + j) % 4] for j in range(len(kinds))]
    gaps = np.diff([t.timestamp() for _, t in a]) / 86400
    assert 6.0 < gaps.min() and gaps.max() < 9.0
    assert 24 <= sum(1 for k, _ in a if k in ("new", "full")) <= 26


def test_signal_mask_first_bar_at_or_after_phase_daily():
    idx = pd.bdate_range("2024-01-02", "2024-02-28")
    m = L.signal_masks(idx, "1d")
    assert idx[np.where(m["full"])[0]].strftime("%Y-%m-%d").tolist() == ["2024-01-25", "2024-02-26"]  # 02-24 full moon is a Saturday
    # new moon 2024-02-09 22:59 UTC = 04:29 IST on Sat 02-10 -> first bar is Monday 02-12
    assert idx[np.where(m["new"])[0]].strftime("%Y-%m-%d").tolist() == ["2024-01-11", "2024-02-12"]


def test_signal_mask_intraday_uses_ist_bar_after_instant():
    idx = pd.date_range("2024-01-25 09:15", "2024-01-26 15:15", freq="15min", tz="Asia/Kolkata")
    mins = idx.hour * 60 + idx.minute
    idx = idx[(mins >= 9 * 60 + 15) & (mins <= 15 * 60 + 15)]
    m = L.signal_masks(idx, "15m")
    pos = np.where(m["full"])[0]
    # instant is 23:25 IST on 01-25, after that day's last bar: first bar at/after is 01-26 09:15
    assert [str(idx[p]) for p in pos] == ["2024-01-26 09:15:00+05:30"]


# ---------------------------------------------------------------- B-112 cells
def _frame(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.005, "Low": np.minimum(o, c) * 0.995,
                         "Close": c, "Volume": 1e6}, index=idx)


def test_cells_both_directions_atr_hold_sweep_and_stop_on_every_cell():
    cells = {}
    L.cells_for_frame(_frame(), "1d", 0.008, cells)
    tags = set(cells)
    for var in L.VARIANTS:
        for d in ("long", "short"):
            for k in L.KS:
                for hd in L.HOLD_DAYS:
                    assert L.tag(var, d, "1d", k, hd) in tags
    assert all("atrnone" not in t for t in tags)
    for t in tags:
        parts = t.split("__")
        assert len(parts) == 6 and parts[5] == "v1" and parts[0] == "lunar" and parts[2] in ("long", "short")
        assert parts[4].split("_")[0].startswith("atr") and parts[4].split("_")[1].startswith("hd")
    res = orx.finalize(cells, min_n=1)
    assert res[L.tag("full", "long", "1d", 2.5, 5)]["n"] >= 1


def test_pair_pooled_is_sum_of_legs_and_merge_roundtrip(tmp_path, monkeypatch):
    cells = {}
    L.cells_for_frame(_frame(), "1d", 0.008, cells)
    out = L.pooled_pair(cells)
    t = L.tag("full", "long", "1d", 1.5, 3).replace("lunar__full__long", "lunar__pair__bidirectional")
    assert t in out
    a, b = cells[L.tag("full", "long", "1d", 1.5, 3)], cells[L.tag("new", "short", "1d", 1.5, 3)]
    assert out[t]["n"] == a["n"] + b["n"]
    shard = tmp_path / "lunar_1d_s0.json"
    shard.write_text(json.dumps({"interval": "1d", "period": "5y", "shard": 0, "universe_requested": 1, "symbols": 1,
                                 "cost_round_trip": 0.008, "events": {"full": 2, "new": 2, "quarter": 4},
                                 "cells": cells, "fetched_symbols": ["X.NS"]}))
    monkeypatch.setenv("OUT", str(tmp_path / "r.json"))
    monkeypatch.setenv("TSV_OUT", str(tmp_path / "c.tsv"))
    res = L.merge([str(shard)])
    assert any(k.startswith("lunar__pair__bidirectional__") for k in res)
    assert json.load(open(tmp_path / "r.json"))["fetched_symbols"] == ["X.NS"]
    assert (tmp_path / "c.tsv").read_text().splitlines()[0].startswith("tag\t")


def test_lunar_workflow_dispatch_ready():
    w = _wf("lunar-sweep.yml")
    inp = w["on"]["workflow_dispatch"]["inputs"]
    assert {"intervals", "period", "maxsym", "pin_run_id", "pin_artifact"} <= set(inp)
    default_intervals = json.loads(inp["intervals"]["default"])
    assert default_intervals == ["1d", "4h", "1h", "15m", "5m"]
    shards = w["jobs"]["run"]["strategy"]["matrix"]["shard"]
    assert len(default_intervals) * len(shards) + 1 < 40
    txt = (WF / "lunar-sweep.yml").read_text()
    assert "scripts/lunar_sweep.py" in txt and "lunar-results" in txt and 'NSHARDS: "4"' in txt
    assert w["jobs"]["merge"]["needs"] == "run"


# ---------------------------------------------------------------- B-786
def test_oneil_retag_and_workflow_inputs():
    spec = importlib.util.spec_from_file_location("oneil_replay", R / "scripts" / "oneil_replay.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    t = "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v1"
    assert rp.retag_tf(t, "1d") == t.replace("__1w__", "__1d__")
    assert rp.parse_tag(rp.retag_tf(t, "1d"))["tf"] == "1d"
    with pytest.raises(ValueError):
        rp.retag_tf(t, "15m")   # bar-count constants are weeks/days: intraday flagged, not faked
    w = _wf("oneil-replay.yml")
    assert {"tags", "interval", "period"} <= set(w["on"]["workflow_dispatch"]["inputs"])
    assert len(w["jobs"]["scan"]["strategy"]["matrix"]["shard"]) + 1 < 40
    txt = (WF / "oneil-replay.yml").read_text()
    assert "INTERVAL: ${{ inputs.interval }}" in txt and "PERIOD: ${{ inputs.period }}" in txt


def test_kalman_replay_workflow_has_interval_and_period_inputs():
    w = _wf("intraday-flatten-rerun.yml")
    assert {"families", "intervals", "period"} <= set(w["on"]["workflow_dispatch"]["inputs"])
    m = w["jobs"]["run"]["strategy"]["matrix"]
    assert 1 * 2 * len(m["shard"]) + 1 < 40          # chan_kalman x (5m, 15m) x 3 shards + merge
    assert "PERIOD: ${{ inputs.period }}" in (WF / "intraday-flatten-rerun.yml").read_text()
    assert 'os.environ.get("PERIOD")' in (R / "scripts" / "intraday_flatten_rerun.py").read_text()


def test_main_has_no_oneil_function_yet_and_kalman_short_port_landed():
    """Evidence guard for B-786, flipped for kalman by B-913 (2026-10-13): main.py now carries the verbatim
    chan_kalman short PORT (tests/test_chan_kalman_short_port.py proves parity); the replay must be switched to import it
    before anything is wired. The oneil guard stands until that port lands."""
    src = (R / "main.py").read_text().lower()
    assert "oneil" not in src
    assert "def chan_kalman_band_short_entry_signal" in src


# ---------------------------------------------------------------- B-541
def test_rolling_monitor_policy_matches_row():
    import rolling_monitor as rm
    assert rm.should_alert([-1.0] * 12 + [0.5] * 8)[0] is True
    assert rm.should_alert([1.0, -0.5] * 10)[0] is False
