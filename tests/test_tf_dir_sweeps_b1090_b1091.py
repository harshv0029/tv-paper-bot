import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import tf_sweep_common as C  # noqa: E402
import island_tf_dir_sweep_replay as I  # noqa: E402
import pl1d_tf_dir_sweep_replay as P  # noqa: E402
import island_main_replay as IM  # noqa: E402
import main  # noqa: E402


@pytest.fixture
def restore_pl1d():
    a, b = dict(main.PL1D_CELLS), dict(main.PL1D_SHORT_CELLS)
    yield
    main.PL1D_CELLS.clear(); main.PL1D_CELLS.update(a)
    main.PL1D_SHORT_CELLS.clear(); main.PL1D_SHORT_CELLS.update(b)


def test_tags_follow_grammar():
    assert I.make_tag("gap05", "short", "15m", 1.5) == "reversal__island_gap05__short__15m__atr1d5_within8__nonovl__v2"
    assert I.make_tag("none", "short", "1d", 1.5) == main.ISLAND_SHORT_NONE_TAG  # cross-check name = registry name
    assert P.make_tag("starc_fade", "short", "1h", 2.5) == "starc__fade_full__short__1h__atr2d5_h20__v1"
    assert P.make_tag("gap_runaway", "long", "5m", 4) == "gap__runaway__long__5m__atr4_h20__v1"
    assert len(I.cell_specs("4h", [1.5, 2.5, 4.0])) == 24
    assert len(P.cell_specs("4h", [2.5, 4, 6], 20)) == 12


def test_sl_on_every_trade_atrnone_refused():
    for bad in ("0", "-2", "none"):
        with pytest.raises(ValueError):
            C.parse_atrs(bad, (1.5,))
    assert C.parse_atrs("", (1.5, 2.5)) == [1.5, 2.5]


def test_plans_cover_tfs():
    assert {x["tf"] for x in C.plan({}, I.DEFAULT_SHARDS)["include"]} == {"1d", "4h", "1h", "15m", "5m"}
    assert len(C.plan({}, P.DEFAULT_SHARDS)["include"]) == 8 + 8 + 16 + 24


def test_prep_frame_string_dates_sorted_and_4h():
    idx = pd.date_range("2026-01-05 09:15", periods=14, freq="1h", tz="Asia/Kolkata")
    raw = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0}, index=idx)
    h = C.prep_frame(raw, "1h")
    assert h["Date"].iloc[0] == "2026-01-05 09:15" and list(h["Date"]) == sorted(h["Date"])
    f = C.prep_frame(raw, "4h")
    assert len(f) < len(h) and f["Date"].iloc[0] == "2026-01-05 09:15"


def test_island_candidate_prefilter_is_exact():
    df = IM.synthetic_frame(1, 700)
    for flt in ("none",):
        for d in ("short", "long"):
            cand = I.candidate_bars(df, d)
            tag = I.selector_tag(main, flt, d)
            fn = main.island_short_entry_signal if d == "short" else main.island_swing_entry_signal
            for k in range(30, len(df) - 1):
                if fn(df.iloc[:k + 1], tag):
                    assert cand[k]


def test_island_replay_stop_always_attached_and_cost():
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    specs = {t: s for t, s in I.cell_specs("1d", [1.5, 4.0]).items() if s["filter"] == "none"}
    tot = 0
    for seed in range(3):
        res = I.replay_symbol(main, IM.synthetic_frame(seed, 700), specs, cost)
        for tag, trs in res.items():
            for t in trs:
                tot += 1
                assert t["reason"] in ("stop_loss", "rule_exit", "max_hold_timeout", "data_end_forced_close", "protected_stop")
                assert abs(t["net"] - (t["gross"] - cost)) < 1e-12
    assert tot > 0  # synthetic islands fire in both directions


def test_pl1d_replay_registers_in_process_and_runs_real_fns(restore_pl1d):
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    specs = P.cell_specs("1h", [2.5, 6.0], 20)
    P.register_cells(main, specs)
    assert all(t in main.PL1D_CELLS or t in main.PL1D_SHORT_CELLS for t in specs)
    rng = np.random.default_rng(3)
    n = 500
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    o = c * (1 + rng.normal(0, 0.02, n))
    df = pd.DataFrame({"Date": C.date_strings(pd.date_range("2026-01-01 09:15", periods=n, freq="1h"), "1h"),
                       "Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99, "Close": c,
                       "Volume": 1e6})
    res = P.replay_symbol(main, df, specs, cost)
    for tag, trs in res.items():
        for t in trs:
            assert abs(t["net"] - (t["gross"] - cost)) < 1e-12 and t["held"] >= 0
            assert t["reason"] in ("pl1d_stop_loss", "pl1d_max_hold_timeout", "pl1d_short_stop_loss",
                                   "pl1d_short_max_hold_timeout", "data_end_forced_close")


def test_pl1d_ordinal_dates_make_intraday_exit_bar_indexed(restore_pl1d):
    # day-granular exit fn: all bars share one calendar day; only ordinals make 'after entry' mean 'later bars'
    cost = 0.0
    spec = {"rule": "starc_fade", "dir": "long", "tf": "5m", "atr": 2.5, "hold": 3}
    tag = P.make_tag("starc_fade", "long", "5m", 2.5, 3)
    main.PL1D_CELLS[tag] = ("starc_fade", 2.5, 3)
    df = pd.DataFrame({"Date": ["2026-01-05 09:15"] * 6, "Open": [100, 100, 100, 100, 100, 100.0],
                       "High": [101] * 6, "Low": [99] * 6, "Close": [100, 100, 100, 100, 100, 100.0], "Volume": 1.0})
    sig = {"entry_price": 100.0, "stop_loss": 90.0}
    tr, j = P.run_trade(main, df, 0, sig, tag, spec, cost)
    assert j == 3 and tr["reason"] == "pl1d_max_hold_timeout" and tr["held"] == 3


def test_merge_roundtrip(tmp_path, monkeypatch, restore_pl1d):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TF", "1h")
    monkeypatch.setenv("SYMBOL_LIMIT", "2")
    P.run()
    out = C.merge_dir("out", "pl1d", "pl1d_all.json")
    assert len(out["rows"]) == 12 and all("pfnet" in r["metrics"] for r in out["rows"])
    monkeypatch.setenv("TF", "1d")
    I.run()
    out = C.merge_dir("out", "isl", "isl_all.json")
    assert len(out["rows"]) == 24
    assert json.load(open("out/isl_all.json"))["rows"]
