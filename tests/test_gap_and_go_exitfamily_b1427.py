"""B-1427: main.py ports of exit_family_research.simulate() kinds inval (elder / ema13w) and exhaust (roc / volclimax),
parity against the research sim on identical inputs, and a SYNTHETIC=1 smoke of scripts/gap_and_go_exitfamily_replay.py."""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import exit_family_research as er  # noqa: E402
import gap_and_go_exitfamily_replay as gx  # noqa: E402
import main as m  # noqa: E402

PORTED = [{"kind": "inval", "atr": a, "sig": s, "hold": 30} for s in ("elder", "ema13w") for a in (2.5, 6.0)] + \
    [{"kind": "exhaust", "atr": 2.5, "trail": 6.0, "x": x, "hold": 30} for x in ("roc", "volclimax")]


def _frame(seed, n=600, vol=0.03):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0015, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * np.exp(rng.normal(0, 0.01, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    v = rng.integers(1e5, 1e6, n).astype(float)
    v[rng.random(n) < 0.08] *= 8  # volume climaxes
    d = pd.bdate_range("2021-01-01", periods=n)
    df = pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v},
                      index=d)
    return df


def _sim_vs_main(df, i0, cell, S):
    sim = er.simulate(S, i0, cell, force_close_at_end=True)
    got = m.exitfamily_walk(df, df["Date"].iloc[i0], float(df["Close"].iloc[i0]), float(S["atr"][i0]), cell)
    return sim, got


def test_cells_match_requested_tags_and_sim_grammar():
    assert len(m.GAP_AND_GO_EXITFAMILY_CELLS) == 5
    for tag, cell in m.GAP_AND_GO_EXITFAMILY_CELLS.items():
        variant = {"inval": "exitinval", "exhaust": "exitexhaust"}[cell["kind"]]
        assert er.cell_tag("gg_long", {**cell, "variant": variant}, version=2) == tag
    assert m.EXITFAMILY_ATR_N == 14 and m.EXITFAMILY_ROC_MIN == 0.15 and m.EXITFAMILY_VOL_CLIMAX_MULT == 3


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_parity_with_research_sim(seed):
    df = _frame(seed)
    S = er.prepare(df, 1)
    seen = set()
    checked = 0
    for cell in PORTED:
        for i0 in range(60, len(df) - 1, 3):
            if not (np.isfinite(S["atr"][i0]) and S["atr"][i0] > 0):
                continue
            sim, got = _sim_vs_main(df, i0, cell, S)
            assert sim is not None and sim != "rejected"
            gross, held, reason = sim
            if reason == "data_end_forced_close":
                assert got["reason"] is None and got["held"] == held
                continue
            assert got["reason"] == reason, (cell, i0)
            assert got["held"] == held, (cell, i0)
            entry = float(df["Close"].iloc[i0])
            assert (got["fill"] - entry) / entry == pytest.approx(gross, abs=1e-12)
            seen.add((cell["kind"], cell.get("sig") or cell.get("x"), reason))
            checked += 1
    assert checked > 300
    reasons = {r for *_, r in seen}
    assert {"stop_hit", "max_hold_timeout"} <= reasons
    assert ("inval", "elder", "signal_invalidation") in seen
    assert ("inval", "ema13w", "signal_invalidation") in seen


def test_exhaustion_exits_fire_and_match():
    hits = {"roc": 0, "volclimax": 0, "trail": 0}
    for seed in range(5, 15):
        df = _frame(seed, n=400, vol=0.045)
        S = er.prepare(df, 1)
        for cell in PORTED[4:]:
            for i0 in range(60, len(df) - 1, 2):
                sim, got = _sim_vs_main(df, i0, cell, S)
                if sim[2] == "exhaustion_exit":
                    assert got["reason"] == "exhaustion_exit" and got["held"] == sim[1]
                    hits[cell["x"]] += 1
                if sim[2] == "trail_stop_hit":
                    assert got["reason"] == "trail_stop_hit" and got["held"] == sim[1]
                    entry = float(df["Close"].iloc[i0])
                    assert (got["fill"] - entry) / entry == pytest.approx(sim[0], abs=1e-12)
                    hits["trail"] += 1
    assert hits["roc"] > 0 and hits["volclimax"] > 0 and hits["trail"] > 0


def test_day_by_day_prefix_calls_equal_full_walk():
    """The driver calls the walk on df.iloc[:i+1] every day: the first exit must equal the one-shot walk (EMAs seed at
    row 0 in both, so the prefix sees the same flags). Entries start after 30 weeks of history: below that
    main.weekly_ema13_down_flags (live code) returns all-False on a short prefix while the sim, computing on the whole
    5y series, already has flags (disclosed limitation, affects only a symbol's first ~150 bars)."""
    df = _frame(7)
    S = er.prepare(df, 1)
    for cell in PORTED:
        for i0 in (160, 200, 333, 450):
            ep, atr, day = float(df["Close"].iloc[i0]), float(S["atr"][i0]), df["Date"].iloc[i0]
            full = m.exitfamily_walk(df, day, ep, atr, cell)
            step = None
            for i in range(i0 + 1, len(df)):
                r = m.exitfamily_walk(df.iloc[:i + 1], day, ep, atr, cell)
                if r["reason"]:
                    step = r
                    break
            if full["reason"] is None:
                assert step is None
            else:
                assert (step["reason"], step["held"], step["fill"]) == (full["reason"], full["held"], full["fill"])


def test_exit_reason_wrapper_and_stop_level():
    df = _frame(3)
    S = er.prepare(df, 1)
    cell = PORTED[0]
    i0 = 100
    reason, rmc = m.exitfamily_exit_reason(df.iloc[:i0 + 3], df["Date"].iloc[i0], float(df["Close"].iloc[i0]),
                                           float(S["atr"][i0]), float(df["Close"].iloc[i0]), cell)
    assert rmc >= float(df["Close"].iloc[i0])
    assert m.exitfamily_stop_level(cell, 90.0, 2.0, 120.0) == 90.0
    ex = PORTED[-1]
    assert m.exitfamily_stop_level(ex, 90.0, 2.0, 120.0) == pytest.approx(108.0)
    assert m.exitfamily_stop_level(ex, 90.0, 2.0, 95.0) == 90.0


def test_atr_at_entry_matches_sim():
    df = _frame(2)
    S = er.prepare(df, 1)
    for i in (50, 149, 300):
        win = df.iloc[max(0, i + 1 - 150):i + 1]
        assert m.exitfamily_atr_at_entry(win) == pytest.approx(S["atr"][i], rel=1e-12)


def _gap_frame():
    df = _frame(11, n=400, vol=0.015).reset_index(drop=True)
    for k in (120, 250):  # force a gap-and-go signal bar
        pc = df.loc[k - 1, "Close"]
        df.loc[k, "Open"] = pc * 1.04
        df.loc[k, "Close"] = pc * 1.07
        df.loc[k, "High"] = pc * 1.075
        df.loc[k, "Low"] = pc * 1.035
        df.loc[k, "Volume"] = 5e6
    return df


def test_driver_replays_every_tag_both_modes():
    df = _gap_frame()
    sigs = gx.entry_signals(m, df)
    assert 120 in sigs and 250 in sigs
    for md in ("off", "live"):
        for t in gx.tags(m):
            trades = gx.replay_symbol(m, df, t, 0.008, md, sigs)
            assert trades, (t, md)
            for tr in trades:
                assert tr["net"] == pytest.approx(tr["gross"] - 0.008)
                assert tr["held"] >= 1
    assert gx.tags(m)[0] == "gap_and_go"


def test_synthetic_smoke_run_and_merge(tmp_path):
    env = {**os.environ, "SYNTHETIC": "1", "SYMBOL_LIMIT": "2", "SHARD": "0", "NSHARDS": "1", "BAND_CAP": "live",
           "OUT_DIR": str(tmp_path / "out")}
    script = os.path.join(ROOT, "scripts", "gap_and_go_exitfamily_replay.py")
    subprocess.run([sys.executable, script, "run"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    out = json.load(open(tmp_path / "out" / "ggxf_s0.json"))
    assert set(out["modes"]) == {"off", "live"}
    assert set(out["modes"]["off"]) == set(gx.tags(m))
    p = subprocess.run([sys.executable, script, "merge", str(tmp_path / "out"),
                        str(tmp_path / "all.json")], cwd=ROOT, env=env, check=True,
                       capture_output=True, text=True)
    assert "RESULTS_JSON: " in p.stdout and "(CONTROL)" in p.stdout
    res = json.loads(p.stdout.split("RESULTS_JSON: ", 1)[1].strip())
    assert len(res["rows"]) == 6 and res["rows"][0]["control"]
    assert res["rows"][1]["band_tag"].endswith("rsbandfloor_sigelder__v2")


def test_plan_and_workflow():
    assert gx.plan({"NSHARDS": "3"}) == {"include": [{"shard": s, "nshards": 3} for s in range(3)]}
    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "gap-and-go-exitfamily-replay.yml")))
    jobs = wf["jobs"]
    assert jobs["replay"]["strategy"]["max-parallel"] == 4
    assert set(jobs) == {"plan", "replay", "merge"}


def test_ports_not_wired():
    src = open(os.path.join(ROOT, "main.py")).read()
    for name in ("exitfamily_walk(", "GAP_AND_GO_EXITFAMILY_CELLS", "exitfamily_exit_reason("):
        # only the definition block references them (no scan / real-order call site)
        assert src.count(name) <= 3, name
