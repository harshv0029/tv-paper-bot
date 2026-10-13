import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import class_a_replay as R  # noqa: E402
import main  # noqa: E402
import strategy_registry as sr  # noqa: E402


def test_parse_tag_and_cells():
    c = R.parse_sector_tag("sector_rotation__fade__short__1d__atr1d5_h20_l5_n1__v1")
    assert (c["atr"], c["hold"], c["L"], c["N"], c["tf"]) == (1.5, 20, 5, 1, "1d")
    assert R.cell_token(c) == "atr1d5_h20_l5_n1"
    assert [x["atr"] for x in R.parse_cells("atr6d0_h5_l3_n1,atr2d5_h10_l5_n3")] == [6.0, 2.5]
    assert R.parse_sector_tag("sector_rotation__fade__short__1d__atrnone_h5_l5_n1__v1")["atr"] is None


def test_atrnone_refused_no_trade_without_sl():
    with pytest.raises(ValueError):
        R.parse_cells("atrnone_h5_l5_n1")


def test_short_trade_stop_fill_models():
    # entry bar 0, ent 100, stop 105; bar 1 gaps open 108 and trades up through the stop
    O = np.array([100, 108, 107, 106.0]); H = np.array([101, 109, 108, 107.0])
    L = np.array([99, 106, 105, 104.0]); C = np.array([100, 107, 106, 105.0])
    assert R.short_trade(O, H, L, C, 0, 100, 105, 3, "stop") == (105, 2, "stop_hit")
    assert R.short_trade(O, H, L, C, 0, 100, 105, 3, "gap_aware") == (108, 2, "stop_hit")
    assert R.short_trade(O, H, L, C, 0, 100, 105, 3, "close") == (107, 2, "stop_hit")


def test_short_trade_time_exit_and_window_overrun():
    O = H = L = C = np.array([100, 99, 98, 97.0])
    assert R.short_trade(O, H, L, C, 0, 100, 150, 3, "stop") == (98, 3, "max_hold_timeout")
    assert R.short_trade(O, H, L, C, 2, 98, 150, 3, "stop") is None


def test_trade_record_cost_and_direction():
    r = R.trade_record(100, 95, 3, "x", 0.008, "short")
    assert r["gross"] == pytest.approx(0.05) and r["net"] == pytest.approx(0.042)
    assert R.trade_record(100, 105, 1, "x", 0.008, "long")["net"] == pytest.approx(0.042)


def test_view_matches_real_picks_with_dataframes(monkeypatch):
    """The cheap _View must make the REAL main.sector_rotation_picks return exactly what it returns on
    real DataFrames (so the harness's picks ARE main's picks)."""
    import pandas as pd
    rng = np.random.default_rng(1)
    smap = {f"S{i}": ("A" if i < 6 else "B") for i in range(12)}
    monkeypatch.setattr(main, "_sector_map_cache", smap)
    monkeypatch.setattr(main, "SECTOR_ROT_L", 3)
    monkeypatch.setattr(main, "SECTOR_ROT_N", 2)
    closes = {s: 100 * np.cumprod(1 + rng.normal(0.003 if smap[s] == "A" else -0.001, 0.01, 40)) for s in smap}
    dfs = {s: pd.DataFrame({"Close": c}) for s, c in closes.items()}
    views = {s: R._View(c) for s, c in closes.items()}
    assert main.sector_rotation_picks(views) == main.sector_rotation_picks(dfs)


def test_sector_short_end_to_end_synthetic_with_overrides_restored(monkeypatch):
    frames = {f"S{k}": R.synthetic_frame(k, 400) for k in range(12)}
    monkeypatch.setattr(main, "_sector_map_cache", {s: ("A" if i < 6 else "B") for i, s in enumerate(frames)})
    before = (main.SECTOR_ROT_L, main.SECTOR_ROT_N)
    res = R.run_sector_short(main, frames, R.parse_cells("atr2d5_h5_l3_n1"))
    assert (main.SECTOR_ROT_L, main.SECTOR_ROT_N) == before
    cell = res["cells"]["sector_rotation__fade__short__1d__atr2d5_h5_l3_n1__v1"]
    assert set(cell["by_stop_fill"]) == set(R.STOP_FILLS)
    for m in cell["by_stop_fill"].values():
        assert {"n", "win_pct", "pfnet", "pfgross", "avg_held_bars", "exit_reasons"} <= set(m)
    assert res["cost_round_trip_pct"] == 0.8 and res["universe_size"] == 12


def test_minervini_be_replay_has_stop_on_every_trade_and_uses_real_fns():
    df = R.synthetic_frame(3, 700)
    trades = R.replay_minervini_be(main, df, 2.0, 0.008)
    for t in trades:
        assert t["reason"] in {"stop_hit", "max_hold_timeout", "data_end_forced_close"}
        assert t["net"] == pytest.approx(t["gross"] - 0.008)


def test_plan_is_derived_from_registry_and_excludes_wired_and_atrnone():
    plan = R.build_plan(sr.REGISTRY, set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values()))
    modes = {j["mode"] for j in plan["include"]}
    assert "sector_short" in modes and "minervini_lab" in modes and "minervini_be" in modes
    for j in plan["include"]:
        if j["mode"] == "sector_short":
            assert "atrnone" not in j["cells"]
    names = {j["name"] for j in plan["include"] if j["mode"] == "minervini_lab"}
    assert "pct8_hard" in names
    assert not any(x["tag"] for x in plan["skipped"] if "atr1d5_h20_l5_n1" in x["tag"])
    assert len(plan["include"]) <= 40


# ---- B-1002 sector_rotation sweep (L x N x ATR x hold, 1d + 4h, both directions) ----
def test_sweep_cells_grid_tags_and_atrnone_refused():
    cells = R.sweep_cells("4h", [3], [3, 5], ["1d5", "6d0"])
    assert len(cells) == 2 * 1 * 2 * 2 * 3  # dirs x L x N x atr x holds
    tags = {c["tag"] for c in cells}
    assert "sector_rotation__fade__short__4h__atr1d5_h2_l3_n5__v1" in tags
    assert "sector_rotation__momentum__long__4h__atr6d0_h10_l3_n3__v1" in tags
    assert len(tags) == len(cells)  # every variant its own tag, nothing pooled
    assert all(R.parse_sector_tag(c["tag"]) is not None for c in cells if c["dir"] == "short")
    with pytest.raises(ValueError):
        R.sweep_cells("1d", [1], [1], ["none"])


def test_long_trade_stop_fill_models_and_time_exit():
    O = np.array([100, 92, 93, 94.0]); H = np.array([101, 93, 94, 95.0])
    L = np.array([99, 90, 91, 92.0]); C = np.array([100, 91, 93, 94.0])
    assert R.long_trade(O, H, L, C, 0, 100, 95, 3, "stop") == (95, 2, "stop_hit")
    assert R.long_trade(O, H, L, C, 0, 100, 95, 3, "gap_aware") == (92, 2, "stop_hit")
    assert R.long_trade(O, H, L, C, 0, 100, 95, 3, "close") == (91, 2, "stop_hit")
    assert R.long_trade(O, H, L, C, 0, 100, 50, 3, "stop") == (93, 3, "max_hold_timeout")
    assert R.long_trade(O, H, L, C, 2, 100, 50, 3, "stop") is None


def test_fetch_tf_4h_resamples_1h_to_two_session_bars(monkeypatch):
    import pandas as pd
    ix = pd.DatetimeIndex([f"2026-01-05 {h:02d}:15" for h in (9, 10, 11, 12, 13, 14, 15)], tz="Asia/Kolkata")
    raw = pd.DataFrame({"Date": ix, "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0})
    monkeypatch.setattr(main, "fetch_ohlc", lambda s, p, i: raw if (p, i) == ("730d", "1h") else None)
    out = R.fetch_tf(main, "X.NS", "4h")
    assert len(out) == 2 and "Date" in out.columns
    with pytest.raises(ValueError):
        R.fetch_tf(main, "X.NS", "15m")


def test_sweep_end_to_end_synthetic_both_dirs_overrides_untouched(monkeypatch):
    frames = {f"S{k}": R.synthetic_frame(k, 400) for k in range(12)}
    monkeypatch.setattr(main, "_sector_map_cache", {s: ("A" if i < 6 else "B") for i, s in enumerate(frames)})
    before = (main.SECTOR_ROT_L, main.SECTOR_ROT_N)
    cells = R.sweep_cells("1d", [3], [1, 3, 5], ["2d5"], [5])
    res = R.run_sector_sweep(main, frames, cells, "1d")
    assert (main.SECTOR_ROT_L, main.SECTOR_ROT_N) == before
    assert res["cost_round_trip_pct"] == 0.8 and res["universe_size"] == 12 and res["tf"] == "1d"
    tag_s = "sector_rotation__fade__short__1d__atr2d5_h5_l3_n3__v1"
    tag_l = "sector_rotation__momentum__long__1d__atr2d5_h5_l3_n3__v1"
    assert {tag_s, tag_l} <= set(res["cells"])
    for t in (tag_s, tag_l):
        assert set(res["cells"][t]["by_stop_fill"]) == set(R.STOP_FILLS)
    # top-N is a prefix: N=1 signals never exceed N=3, which never exceed N=5
    n = lambda N: res["cells"][f"sector_rotation__fade__short__1d__atr2d5_h5_l3_n{N}__v1"]["n_signals"]
    assert 0 < n(1) <= n(3) <= n(5)
    # short and long share the same real picks
    assert res["cells"][tag_s]["n_signals"] == res["cells"][tag_l]["n_signals"]


def test_sweep_workflow_matrix_is_tf_by_l_and_no_atrnone():
    import yaml
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows", "sector-rotation-sweep.yml")
    job = yaml.safe_load(open(path))["jobs"]["sweep"]
    assert job["strategy"]["matrix"] == {"tf": ["1d", "4h"], "L": ["1", "3", "5"]}
    env = [s for s in job["steps"] if s.get("name") == "Sweep"][0]["env"]
    assert "none" not in env["ATRS"] and env["MODE"] == "sector_sweep"
    assert job["strategy"]["max-parallel"] <= 20
