"""B-1150 pl1d 1h/4h sweep driver and B-1151 brk20 4h support. Offline, synthetic."""
import json
import os
import sys

import numpy as np
import pandas as pd

import main

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import brk20_plan  # noqa: E402
import brk20_replay as br  # noqa: E402
import pl1d_tf_sweep as sw  # noqa: E402


def test_tags_follow_grammar_and_match_existing_1d_style():
    assert sw.tag_for("starc_fade", "long", "4h", 2.5, 20) == "starc__fade_full__long__4h__atr2d5_h20__v1"
    assert sw.tag_for("gap_runaway", "short", "1h", 4.0, 40) == "gap__runaway__short__1h__atr4_h40__v1"
    tags = {sw.tag_for(r, d, tf, a, h) for r in sw.RULES for d in ("long", "short") for tf in ("1h", "4h")
            for a in sw.DEFAULT_ATRS for h in sw.DEFAULT_HOLDS[tf]}
    assert len(tags) == 2 * 2 * 2 * 2 * 3


def _spike_frame():
    """Flat 100 then a +12% spike close: fires starc_fade LONG? (no, that is a fade-DOWN rule) so build both."""
    n = 90
    c = np.full(n, 100.0)
    d = pd.date_range("2024-01-01 09:15", periods=n, freq="h").astype(str)
    return c, d


def _frame(c, d):
    return pd.DataFrame({"Date": d, "Open": c.copy(), "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6})


def test_short_replay_real_functions_stop_is_above_entry_and_same_day_bars_counted():
    c, d = _spike_frame()
    c[70] = 112.0                         # spike up: starc_fade short fires on bar 70
    df = _frame(c, d)
    df.loc[70, "High"] = 113.0
    df.loc[71, "High"] = 130.0            # NEXT bar (same calendar day at 1h) must be able to stop the short
    res = sw.replay_symbol(main, df, "short", (2.5,), (20,), "1h", 0.008)
    trs = res[sw.tag_for("starc_fade", "short", "1h", 2.5, 20)]
    assert trs and trs[0]["reason"] == "pl1d_short_stop_loss" and trs[0]["held"] == 1
    assert trs[0]["gross"] < 0            # stopped out above entry


def test_long_replay_timeout_and_pnl_sign():
    c, d = _spike_frame()
    c[70:] = 85.0                         # sharp drop: starc_fade long fires, then flat recovery path
    df = _frame(c, d)
    res = sw.replay_symbol(main, df, "long", (4.0,), (5,), "1h", 0.008)
    trs = res[sw.tag_for("starc_fade", "long", "1h", 4.0, 5)]
    assert trs
    for t in trs:
        assert abs(t["net"] - (t["gross"] - 0.008)) < 1e-12


def test_synthetic_run_and_merge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("TF", "4h")
    monkeypatch.setenv("SYMBOL_LIMIT", "3")
    monkeypatch.chdir(tmp_path)
    sw.run()
    out = sw.merge(str(tmp_path / "out"), str(tmp_path / "r.json"))
    assert out["synthetic"] is True and out["rows"]
    row = out["rows"][0]
    assert {"n", "pfnet", "win_pct", "avg_held_hours", "exit_reasons"} <= set(row["metrics"])
    assert json.load(open(tmp_path / "r.json"))["rows"]


def test_workflow_input_and_sharding():
    import yaml
    d = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "pl1d-tf-sweep.yml")))
    on = d.get("on") or d.get(True)
    assert on["workflow_dispatch"]["inputs"]["tf"]["options"] == ["4h", "1h"]
    assert d["jobs"]["replay"]["strategy"]["max-parallel"] <= 20


# ---- B-1151 brk20 4h
def test_brk20_plan_accepts_4h_and_period_map():
    inc = brk20_plan.build({"INTERVALS": "4h", "DIRECTIONS": "long,short", "NSHARDS": "2"})["include"]
    assert {i["interval"] for i in inc} == {"4h"} and len(inc) == 4
    assert br.PERIOD_BY_INTERVAL["4h"] == "730d"
    assert br.make_tag("long", "4h", 3, 4) == "brk20_min_rr__main_replay__long__4h__atr3_rr4__v1"


def test_brk20_fetch_4h_resamples_1h_to_session_bars():
    idx = pd.date_range("2024-01-01 09:15", periods=7, freq="h", tz="Asia/Kolkata")  # 09:15..15:15
    raw = pd.DataFrame({"Date": idx, "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0})

    class M:
        @staticmethod
        def fetch_ohlc(sym, period, interval):
            assert (period, interval) == ("730d", "1h")
            return raw
    out = br.fetch_interval(M, "X", "4h")
    assert len(out) == 2 and out["Volume"].tolist() == [40.0, 30.0] and "Date" in out.columns
