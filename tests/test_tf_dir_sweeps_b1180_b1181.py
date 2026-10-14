import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import tf_sweep_common as C  # noqa: E402
import chan_shape_tf_dir_sweep_replay as CS  # noqa: E402
import tasuki_tf_dir_sweep_replay as T  # noqa: E402
import main  # noqa: E402


def _frame(n=500, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({"Date": C.date_strings(pd.date_range("2026-01-01 09:15", periods=n, freq="1h"), "1h"),
                         "Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99, "Close": c, "Volume": 1e6})


def test_tags_follow_grammar_and_match_registry_names():
    assert CS.make_tag("long", "1d", 1.5, 10) == "chan_shape__mom_mr__long__1d__atr1d5_hold10__nonovl__v2"
    assert CS.make_tag("long", "1d", 4.0, 10) == "chan_shape__mom_mr__long__1d__atr4d0_hold10__nonovl__v2" in main.CHAN_SHAPE_CELLS
    assert CS.make_tag("short", "5m", 2.5, 5) == "chan_shape__mom_mr__short__5m__atr2d5_hold5__nonovl__v2"
    assert T.make_tag("etf", "short", "1d", 2.5, 3) in main.TASUKI_SHORT_CELLS
    assert T.make_tag("full", "long", "15m", 6, 3) == "tasuki__gap_full__long__15m__atr6_h3__v1"
    assert len(CS.cell_specs("4h", [1.5, 2.5, 4], [5, 10])) == 12 and len(T.cell_specs("etf", "4h", [2.5, 4, 6], [3])) == 6


def test_stop_on_every_trade_and_plans():
    for bad in ("0", "-1", "none"):
        with pytest.raises(ValueError):
            C.parse_atrs(bad, (1.5,))
    with pytest.raises(ValueError):
        CS.parse_holds("0")
    p = T.plan({})["include"]
    assert len([x for x in p if x["univ"] == "etf"]) == 5 and len([x for x in p if x["univ"] == "full"]) == 60
    assert {x["tf"] for x in C.plan({}, CS.DEFAULT_SHARDS)["include"]} == {"1d", "4h", "1h", "15m", "5m"}


def test_inverted_frame_is_an_involution_and_flips_order():
    df = _frame(50)
    inv = C.inverted_frame(df)
    back = C.inverted_frame(inv)
    assert np.allclose(back[["Open", "High", "Low", "Close"]].to_numpy(), df[["Open", "High", "Low", "Close"]].to_numpy())
    assert (inv["High"] >= inv["Low"]).all()


def test_tasuki_long_mirror_detects_exact_bullish_pattern():
    # bullish upside tasuki gap on original prices: up candle, gap up, up candle, then down candle opening inside 2nd body and
    # closing back above the first bar's high (gap stays open)
    o = [100.0, 106.0, 108.0]
    c = [103.0, 109.0, 105.0]
    h = [104.0, 110.0, 109.0]
    l = [99.0, 105.0, 104.5]
    # bar0 up (c>o); bar1 low 105 > bar0 high 104 (gap) and up; bar2 down, opens inside bar1 body (108 in 106..109), closes above bar0 high
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c})
    inv = C.inverted_frame(df)
    # mirror of the real short signal on the inverted frame, evaluated on bars 0..2
    assert main.tasuki_short_signal(inv.iloc[0:3]) is True
    assert main.tasuki_short_signal(df.iloc[0:3]) is False


def test_tasuki_long_exit_mapping_matches_gap_aware_low_stop():
    df = pd.DataFrame({"Open": [100.0, 99.0, 90.0], "High": [101.0, 100.0, 91.0], "Low": [99.0, 98.0, 89.0],
                       "Close": [100.0, 99.5, 90.5]})
    inv = C.inverted_frame(df)
    stop_long = 95.0
    res = main.tasuki_short_exit_reason(inv.iloc[1:3], 1.0 / stop_long, 3)
    # bar 2 gaps down through the long stop (low 89 <= 95): long fill = min(open 90, stop 95) = 90
    assert res[0] == "stop_hit" and abs(1.0 / res[1] - 90.0) < 1e-9


def test_replays_run_real_fns_both_directions():
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    tot = 0
    for seed in range(4):
        df = _frame(600, seed)
        for tr in CS.replay_symbol(main, df, CS.cell_specs("1h", [1.5, 4.0], [5]), cost).values():
            for t in tr:
                tot += 1
                assert abs(t["net"] - (t["gross"] - cost)) < 1e-12 and t["held"] >= 1
        for tr in T.replay_symbol(main, df, T.cell_specs("full", "1h", [2.5], [3]), cost).values():
            for t in tr:
                assert abs(t["net"] - (t["gross"] - cost)) < 1e-12
    assert tot > 0


def test_chan_short_is_mirror_of_long_on_inverted_frame():
    df = _frame(600, 1)
    inv = C.inverted_frame(df)
    tag = min(main.CHAN_SHAPE_CELLS, key=lambda t: main.CHAN_SHAPE_CELLS[t][0])
    c = df["Close"].to_numpy(float)
    for k in range(60, 580):
        sig = main.chan_shape_long_entry_signal(inv.iloc[max(0, k - 399):k + 1], tag)
        if sig:
            assert c[k] > c[k - 30] and c[k] < c[k - 40]


def test_merge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TF", "1d")
    monkeypatch.setenv("SYMBOL_LIMIT", "2")
    CS.run()
    assert len(C.merge_dir("out", "cshape", "cshape_all.json")["rows"]) == 12
    monkeypatch.setenv("UNIV", "full")
    T.run()
    out = C.merge_dir("out", "tasuki", "tasuki_all.json")
    assert len(out["rows"]) == 6 and json.load(open("out/tasuki_all.json"))["rows"]
