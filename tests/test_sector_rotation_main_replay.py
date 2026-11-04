"""B-1467: sector_rotation cell family ported into main.py (UNWIRED) + the main-calling replay driver.

Parity: scripts/sector_rotation_backtest.py (the research harness behind the registry numbers) and
scripts/sector_rotation_main_replay.py (real main.py fns) produce the same trades on synthetic data when the replay runs
in the research's own convention (independent overlapping trades, next-open entry, stop fill at the stop)."""
import importlib.util
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import main  # noqa: E402
import sector_rotation_main_replay as R  # noqa: E402


def _load_research():
    spec = importlib.util.spec_from_file_location("sector_rotation_backtest_t", os.path.join(ROOT, "scripts", "sector_rotation_backtest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _universe(T=360, sectors=3, per=8, seed=7):
    """Each sector: half the names drift up, half down for the first 45 bars (breadth 0.5 -> no signal on either side,
    so neither implementation's warm-up rule decides anything), then independent random walks."""
    rng = np.random.default_rng(seed)
    syms, smap, frames = [], {}, {}
    d = pd.bdate_range("2023-01-02", periods=T).strftime("%Y-%m-%d")
    for s in range(sectors):
        for k in range(per):
            sym = f"S{s}K{k}.NS"
            r = rng.normal(0.0003 * (s - 1), 0.02, T)
            r[:45] = 0.004 if k < per // 2 else -0.004
            c = 100 * np.exp(np.cumsum(r))
            o = c * (1 + rng.normal(0, 0.005, T))
            hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, T)))
            lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, T)))
            frames[sym] = pd.DataFrame({"Date": d, "Open": o, "High": hi, "Low": lo, "Close": c})
            syms.append(sym)
            smap[sym] = f"SEC{s}"
    return sorted(syms), smap, frames


@pytest.fixture
def sector_map(monkeypatch):
    syms, smap, frames = _universe()
    monkeypatch.setattr(main, "_sector_map_cache", dict(smap))
    return syms, smap, frames


def _research_results(mod, syms, smap, frames, fade, tmp_path):
    arr = {f: np.column_stack([frames[s][f].to_numpy(float) for s in syms]) for f in ("Open", "High", "Low", "Close")}
    mod.load = lambda: (list(syms), {s: {"sector": smap[s]} for s in syms}, None, arr)
    mod.FADE = fade
    mod.VARIANT = "fade" if fade else "momentum"
    mod.TF = "1d"
    mod.BAR_H = 6.25
    mod.LS, mod.NS, mod.HS, mod.KS = (1, 3, 5), (1, 3, 5), (1, 5, 10, 20), (1.5, 2.5)
    mod.OUT = str(tmp_path / f"res_{int(fade)}.json")
    mod.main()
    import json
    return json.load(open(mod.OUT))["results"]


def test_parity_with_research_harness(sector_map, tmp_path):
    syms, smap, frames = sector_map
    mod = _load_research()
    research = {}
    for fade in (False, True):
        research.update(_research_results(mod, syms, smap, frames, fade, tmp_path))
    groups = [{"side": sd, "L": L, "N": N, "holds": [1, 5, 10, 20]} for sd in ("strong", "weak") for L in (1, 3, 5) for N in (1, 3, 5)]
    out = R.run_cells(main, frames, groups, ["1d5", "2d5"], "1d", one_position=False, fills=("stop",))
    mine = {r["source_tag"]: r["metrics"] for r in out["rows"]}
    compared = 0
    for tag, rm in research.items():
        assert tag in mine, tag
        mm = mine[tag]
        assert mm["n"] == rm["n"], (tag, mm["n"], rm["n"])
        assert mm["pfnet"] == pytest.approx(rm["pfnet"], abs=1.5e-3), tag
        assert mm["win_pct"] == pytest.approx(rm["win_pct"], abs=0.11), tag
        compared += 1
    assert compared >= 60  # every direction x side x L x N x hold x stop the research emitted (n >= 30)
    for d in ("long", "short"):
        for v in ("momentum", "fade"):
            assert any(f"__{v}__{d}__" in t for t in research), (v, d)


def test_one_position_per_symbol_never_overlaps(sector_map):
    syms, smap, frames = sector_map
    groups = [{"side": "strong", "L": 3, "N": 3, "holds": [10]}, {"side": "weak", "L": 3, "N": 3, "holds": [10]}]
    syms_, dates, P = R.build_panel(main, frames)
    sigs = R.compute_signals(main, syms_, P["C"], groups)
    for (side, L), sl in sigs.items():
        for d in ("long", "short"):
            tr = R.simulate(main, P, sl, 3, d, 2.5, 10, "gap_aware", 0.008, one_position=True)
            free = R.simulate(main, P, sl, 3, d, 2.5, 10, "gap_aware", 0.008, one_position=False)
            assert 0 < len(tr) < len(free)


def test_one_position_intervals_disjoint():
    m = types.SimpleNamespace(
        sector_rotation_cell_stop=main.sector_rotation_cell_stop,
        sector_rotation_cell_exit_reason=main.sector_rotation_cell_exit_reason)
    T = 40
    c = np.full((T, 1), 100.0)
    P = {"O": c.copy(), "H": c + 1, "L": c - 1, "C": c.copy(), "ATR": np.full((T, 1), 2.0)}
    sl = [(t, 0, 0) for t in range(0, 30)]  # a signal every bar on the same symbol
    tr = R.simulate(m, P, sl, 1, "long", 4.0, 5, "stop", 0.0, one_position=True)
    es = [x["e"] for x in tr]
    assert es == [1, 6, 11, 16, 21, 26]  # bar after each 5-bar exit; signals end at t=29
    for a, b in zip(tr, tr[1:]):
        assert b["e"] >= a["e"] + a["held"]


def test_weak_picks_and_side_mapping(monkeypatch):
    smap = {f"A{i}": "A" for i in range(5)} | {f"B{i}": "B" for i in range(5)}
    monkeypatch.setattr(main, "_sector_map_cache", smap)
    dfs = {}
    for i in range(5):
        dfs[f"A{i}"] = pd.DataFrame({"Close": [100.0] * 20 + [100 - (i + 1)]})  # all down: breadth 0
        dfs[f"B{i}"] = pd.DataFrame({"Close": [100.0] * 20 + [100 + (i + 1)]})  # all up: breadth 1
    assert main.sector_rotation_weak_picks(dfs, 1, 2) == ["A4", "A3"]
    assert main.sector_rotation_picks(dfs, L=1, N=2) == ["B4", "B3"]
    assert main.sector_rotation_cell_picks(dfs, "momentum", "long", 1, 2) == ["B4", "B3"]
    assert main.sector_rotation_cell_picks(dfs, "fade", "short", 1, 2) == ["B4", "B3"]
    assert main.sector_rotation_cell_picks(dfs, "momentum", "short", 1, 2) == ["A4", "A3"]
    assert main.sector_rotation_cell_picks(dfs, "fade_n200", "long", 1, 2) == ["A4", "A3"]
    with pytest.raises(ValueError):
        main.sector_rotation_cell_side("other", "long")


def test_weak_picks_need_low_breadth(monkeypatch):
    smap = {f"A{i}": "A" for i in range(5)}
    monkeypatch.setattr(main, "_sector_map_cache", smap)
    dfs = {f"A{i}": pd.DataFrame({"Close": [100.0] * 20 + [100 + (1 if i < 3 else -1)]}) for i in range(5)}
    assert main.sector_rotation_weak_picks(dfs, 1, 3) == []  # breadth 0.6 > 0.4


def test_cell_stop_and_exit_long_fills():
    assert main.sector_rotation_cell_stop(100, 2, 2.5, "long") == pytest.approx(95)
    assert main.sector_rotation_cell_stop(100, 2, 2.5, "short") == pytest.approx(105)
    assert main.sector_rotation_cell_stop(100, 2, None, "long") is None
    assert main.sector_rotation_cell_stop(10, 5, 6, "long") is None  # stop <= 0: no entry
    bars = {"Open": [100, 94, 99], "High": [101, 95, 100], "Low": [99, 93, 98], "Close": [100, 94.5, 99]}
    assert main.sector_rotation_cell_exit_reason(bars, 95, 3, "long", "stop") == ("stop_hit", 95.0, 2)
    assert main.sector_rotation_cell_exit_reason(bars, 95, 3, "long", "gap_aware") == ("stop_hit", 94.0, 2)
    assert main.sector_rotation_cell_exit_reason(bars, 95, 3, "long", "close") == ("stop_hit", 94.5, 2)
    assert main.sector_rotation_cell_exit_reason(bars, 90, 3, "long", "stop") == ("max_hold_timeout", 99.0, 3)
    assert main.sector_rotation_cell_exit_reason(bars, 90, 4, "long", "stop") is None
    with pytest.raises(ValueError):
        main.sector_rotation_cell_exit_reason(bars, 90, 3, "long", "bogus")
    sb = {"Open": [100, 106], "High": [101, 107], "Low": [99, 105], "Close": [100, 106]}
    assert main.sector_rotation_cell_exit_reason(sb, 105, 2, "short", "gap_aware") == ("stop_hit", 106.0, 2)


def test_tags_and_plan():
    c = R.parse_tag("sector_rotation__fade_n200__long__1d__atr6d0_h20_l5_n5__v1")
    assert c == {"var": "fade", "uni": "n200", "dir": "long", "tf": "1d", "atr_tok": "6d0", "hold": 20, "L": 5, "N": 5}
    assert R.parse_tag("sector_rotation__momentum__long__4h__atr6d0_h10_l3_n1_ec1__v1") is None
    t = R.new_tag("momentum", "", "short", "4h", "2d5", "gap_aware", 6, 5, 1)
    assert t == "sector_rotation__momentum_main1p__short__4h__atr2d5_flgap_h6_l5_n1__v1"
    assert "_ec1_" in R.new_tag("fade", "n200", "long", "1d", "6d0", "stop", 20, 1, 5, "signal_close")
    M = types.SimpleNamespace

    def s(name, v=True):
        return M(name=name, is_viable=lambda: v)
    reg = [s("sector_rotation__fade__short__1d__atr2d5_h10_l3_n1__v1"),
           s("sector_rotation__momentum__short__1d__atrnone_h20_l3_n1__v1"),
           s("sector_rotation__fade__long__1d__atr4d0_h20_l5_n5__v1", False),
           s("sector_rotation__momentum__long__1d__atr6d0_h20_l1_n5__v1"),
           s("sector_rotation__momentum__long__1h__atr2d5_h6_l5_n1__v1"),
           s("sector_rotation__weird__long__1d__x__v1")]
    plan = R.build_plan(reg, {"sector_rotation__momentum__long__1d__atr6d0_h20_l1_n5__v1"})
    inc = {j["name"]: j for j in plan["include"]}
    assert set(inc) == {"1d", "1h"}
    assert R.parse_groups(inc["1d"]["groups"]) == [{"side": "strong", "L": 3, "N": 1, "holds": [10]},
                                                    {"side": "weak", "L": 3, "N": 1, "holds": [20]}]
    assert plan["stop_substituted"] == ["sector_rotation__momentum__short__1d__atrnone_h20_l3_n1__v1"]
    assert plan["skipped"][0]["tag"] == "sector_rotation__weird__long__1d__x__v1"
    assert "none" not in inc["1d"]["atrs"]


def test_atrnone_refused(sector_map):
    _, _, frames = sector_map
    with pytest.raises(ValueError):
        R.run_cells(main, frames, [{"side": "strong", "L": 1, "N": 1, "holds": [5]}], ["none"], "1d")


def test_rows_emit_every_field(sector_map):
    _, _, frames = sector_map
    out = R.run_cells(main, frames, [{"side": "weak", "L": 5, "N": 3, "holds": [5]}], ["2d5"], "1d")
    assert len(out["rows"]) == 2 * 3  # both directions x three fills
    r = out["rows"][0]
    for k in ("n", "pfnet", "pfgross", "win_pct", "avg_held_bars", "avg_held_hours", "exit_reasons", "is", "oos"):
        assert k in r["metrics"]
    assert r["metrics"]["n"] == r["metrics"]["is"]["n"] + r["metrics"]["oos"]["n"]
    assert {x["direction"] for x in out["rows"]} == {"long", "short"}
    assert all("_main1p__" in x["tag"] for x in out["rows"])


def test_workflow_uploads_single_merged_json():
    y = open(os.path.join(ROOT, ".github", "workflows", "sector-rotation-main-replay.yml")).read()
    assert "sector_rotation_main_replay.py plan" in y and "sector_rotation_main_replay.py merge" in y
    assert "path: sector_rotation_main_replay_all.json" in y
    assert "SECTOR_GROUPS" in y  # never GROUPS: a bash special variable


def test_ported_functions_are_unwired():
    src = open(os.path.join(ROOT, "main.py")).read()
    a = src.index("# ---- B-1467: sector rotation cell family")
    b = src.index("def sector_rotation_exit_reason(df, entry_day")
    rest = src[:a] + src[b:]
    for fn in ("sector_rotation_weak_picks", "sector_rotation_cell_picks", "sector_rotation_cell_stop",
               "sector_rotation_cell_exit_reason", "sector_rotation_cell_side"):
        assert fn not in rest, fn  # defined only; never called from a scan, paper or real path
