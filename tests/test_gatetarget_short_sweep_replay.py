import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import gatetarget_short_sweep_replay as G  # noqa: E402
import brk20_replay as B  # noqa: E402
import main  # noqa: E402


def test_tag_grammar_and_cells():
    assert G.make_tag("4h", 3.0) == "swingminrr__brk20_gatetarget__short__4h__atr3_h30_rr4__v1"
    assert G.make_tag("5m", 1.5, 4, 20) == "swingminrr__brk20_gatetarget__short__5m__atr1d5_h20_rr4__v1"
    specs = G.cell_specs("15m", G.parse_atrs("2,3,4,6"), 4.0, 30)
    assert len(specs) == 4 and len(set(specs)) == 4


def test_atr_must_be_positive_sl_on_every_trade():
    for bad in ("0", "-1", "", "none"):
        with pytest.raises(ValueError):
            G.parse_atrs(bad)


def test_plan_covers_three_tfs_sharded():
    p = G.plan({})["include"]
    assert {x["tf"] for x in p} == {"4h", "15m", "5m"}
    assert len(p) == 8 + 16 + 24


def test_replay_runs_real_main_fns():
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    spec = next(iter(G.cell_specs("4h", [3.0], 4.0, 30).values()))
    for seed in range(12):
        for t in G.replay_symbol(main, B.synthetic_frame(seed, 700), spec, cost):
            assert t["reason"] in ("stop_hit", "target_hit", "max_hold_timeout", "data_end_forced_close")
            assert abs(t["net"] - (t["gross"] - cost)) < 1e-12


def test_candidate_prefilter_is_exact_for_real_signal():
    df = B.synthetic_frame(3, 700)
    lows, closes = df["Low"].to_numpy(float), df["Close"].to_numpy(float)
    pm = pd.Series(lows).shift(1).rolling(20).min().to_numpy()
    for k in range(70, len(df)):
        sig = main.brk20_min_rr_entry_signal(df.iloc[max(0, k + 1 - 200):k + 1], "short", 3.0, 4.0)
        if sig:
            assert closes[k] < pm[k]


def test_merge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TF", "4h")
    monkeypatch.setenv("SYMBOL_LIMIT", "3")
    G.run()
    out = G.merge("out")
    assert len(out["rows"]) == 4 and all("pfnet" in r["metrics"] for r in out["rows"])
    assert json.load(open("out/gts_all.json"))["rows"]
