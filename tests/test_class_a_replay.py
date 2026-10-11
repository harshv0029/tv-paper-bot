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
