"""Tests for scripts/exit_family_research.py (B-529/B-538/B-493/B-740 exit-family harness)."""
import importlib.util
import json
import pathlib
import re

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "exit_family_research", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "exit_family_research.py")
ef = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ef)


def _df(n=320, seed=3, drift=0.0005):
    rng = np.random.default_rng(seed)
    px = 100.0
    rows = []
    for _ in range(n):
        o = px
        c = px * (1 + rng.normal(drift, 0.015))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.006)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.006)))
        rows.append((o, h, l, c, 100000 + rng.integers(0, 50000)))
        px = c
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def test_tags_follow_grammar_unique_and_cover_entry_sets():
    tags = [ef.cell_tag(k, c) for k in ef.ENTRY_SETS for c in ef.CELLS]
    assert len(tags) == len(set(tags)) == len(ef.ENTRY_SETS) * len(ef.CELLS)
    for t in tags:
        assert re.fullmatch(r"[a-z0-9_]+", t) and t.endswith("__v1")
        assert len(t.split("__")) == 6
    assert any("__short__1d__" in t for t in tags) and any("__long__1d__" in t for t in tags)
    assert "atr2d5" in ef.cell_tag("gg_long", {"kind": "fixed", "variant": "exitfixed", "atr": 2.5, "hold": 30})


def test_every_cell_carries_a_stop():
    for c in ef.CELLS:
        assert c["kind"] == "struct" or c.get("atr", 0) > 0


def _S(o, h, l, c, atr=1.0):
    n = len(c)
    z = np.zeros(n, bool)
    return {"o": np.array(o, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float),
            "v": np.full(n, 1000.0), "atr": np.full(n, atr), "rsi": np.full(n, 50.0),
            "roc": np.full(n, np.nan), "vavg": np.full(n, 1000.0),
            "inval": {"ema13w": z.copy(), "macdhw": z.copy(), "elder": z.copy()}}


def test_fixed_stop_hit_and_gap_through_fill():
    # entry 100, atr 1, stop 97.5 ; bar1 opens below stop -> fills at open
    S = _S([100, 96, 96, 96, 96], [100, 97, 97, 97, 97], [100, 95, 95, 95, 95], [100, 96, 96, 96, 96])
    cell = {"kind": "fixed", "atr": 2.5, "hold": 3}
    g, held, reason = ef.simulate(S, 0, cell)
    assert reason == "stop_hit" and held == 1 and abs(g - (-0.04)) < 1e-9
    # intrabar touch fills at the stop
    S = _S([100, 100, 100, 100, 100], [100, 101, 101, 101, 101], [100, 97, 99, 99, 99], [100, 100, 100, 100, 100])
    g, held, reason = ef.simulate(S, 0, cell)
    assert reason == "stop_hit" and abs(g + 0.025) < 1e-9


def test_time_stop_and_max_hold_and_truncated_trade_dropped():
    n = 8
    flat = [100.0] * n
    S = _S(flat, [101] * n, [99.5] * n, flat)
    assert ef.simulate(S, 0, {"kind": "time", "atr": 2.5, "hold": 5})[2] == "time_stop"
    assert ef.simulate(S, 0, {"kind": "fixed", "atr": 2.5, "hold": 5})[2] == "max_hold_timeout"
    assert ef.simulate(S, 5, {"kind": "fixed", "atr": 2.5, "hold": 5}) is None  # runs past data end


def test_structural_rejected_when_no_stop_below_entry():
    # entry bar is also the lowest low of window with entry == low -> stop = low - pad < entry still ok;
    # make low above entry (impossible data) to force rejection
    S = _S([100] * 6, [101] * 6, [100.5] * 6, [100] * 6)
    assert ef.simulate(S, 3, {"kind": "struct", "sw": 3, "hold": 2}) == "rejected"
    S = _S([100] * 6, [101] * 6, [98] * 6, [100] * 6)
    assert ef.simulate(S, 3, {"kind": "struct", "sw": 3, "hold": 2})[2] == "max_hold_timeout"


def test_chandelier_trail_locks_profit():
    c = [100, 104, 108, 112, 110, 109.5, 100, 100, 100]
    S = _S(c, [x + 0.5 for x in c], [x - 0.5 for x in c], c)
    r = ef.simulate(S, 0, {"kind": "chand", "atr": 2.5, "trail": 3.0, "hold": 8})
    assert r[2] == "trail_stop_hit" and r[0] > 0.04  # trail at 112-3=109 -> exit near +9%


def test_exhaustion_volume_climax_exit():
    c = [100, 102, 104, 103, 103, 103, 103]
    o = [100, 101, 103, 105, 103, 103, 103]
    S = _S(o, [x + 1 for x in c], [x - 1 for x in c], c)
    S["v"] = np.array([1000, 1000, 1000, 5000, 1000, 1000, 1000], float)
    r = ef.simulate(S, 0, {"kind": "exhaust", "atr": 2.5, "trail": 6.0, "x": "volclimax", "hold": 6})
    assert r[2] == "exhaustion_exit" and r[1] == 3


def test_signal_invalidation_fires_on_transition_only():
    n = 8
    flat = [100.0] * n
    S = _S(flat, [101] * n, [99.5] * n, flat)
    S["inval"]["ema13w"] = np.array([0, 0, 0, 1, 1, 1, 1, 1], bool)
    r = ef.simulate(S, 0, {"kind": "inval", "sig": "ema13w", "atr": 2.5, "hold": 6})
    assert r[2] == "signal_invalidation" and r[1] == 3
    S["inval"]["ema13w"] = np.ones(n, bool)  # already bearish at entry, never transitions
    assert ef.simulate(S, 0, {"kind": "inval", "sig": "ema13w", "atr": 2.5, "hold": 6})[2] == "max_hold_timeout"


def test_oneil_swing_low_ratchets_stop_up():
    c = [100, 105, 110, 106, 108, 112, 114, 108, 108, 108]
    l = [99, 104, 109, 103, 107, 111, 113, 106, 106, 106]
    h = [x + 1 for x in c]
    S = _S(c, h, l, c)
    r = ef.simulate(S, 0, {"kind": "oneil", "atr": 2.5, "w": 1, "hold": 8})
    # swing low 103 (bar3) confirmed -> stop ~102.9 ; bar7 low 106 > stop, later bars no hit -> timeout
    assert r[2] == "max_hold_timeout"
    S["l"][7] = 102.0
    r = ef.simulate(S, 0, {"kind": "oneil", "atr": 2.5, "w": 1, "hold": 8})
    assert r[2] == "trail_stop_hit" and r[0] > 0.02  # fixed 2.5-ATR stop (97.5) would have given -2.5%


def test_short_orientation_is_exact_mirror_of_long():
    df = _df()
    mirror = df.copy()
    mirror[["Open", "High", "Low", "Close"]] = 1000.0 - 0 * df[["Open", "High", "Low", "Close"]]
    SL = ef.prepare(df, +1)
    SS = ef.prepare(df, -1)
    assert np.allclose(SS["c"], -SL["c"]) and np.allclose(SS["h"], -SL["l"]) and np.allclose(SS["l"], -SL["h"])
    # a drifting-down path must be a winner for the short cell, a loser for the long cell
    n = 12
    c = np.linspace(100, 80, n)
    dd = pd.DataFrame({"Open": c, "High": c + 0.2, "Low": c - 0.2, "Close": c, "Volume": 1000.0},
                      index=pd.bdate_range("2024-01-01", periods=n))
    SLd, SSd = ef.prepare(dd, +1), ef.prepare(dd, -1)
    cell = {"kind": "fixed", "atr": 2.5, "hold": 8}
    SLd["atr"][:] = 1.0
    SSd["atr"][:] = 1.0
    assert ef.simulate(SLd, 1, cell)[0] < 0 < ef.simulate(SSd, 1, cell)[0]


def test_accumulate_summarize_merge_and_net_cost():
    a, b = ef.new_acc(), ef.new_acc()
    ef.add_trade(a, 0.10, 5, "max_hold_timeout", 0.008)
    ef.add_trade(a, -0.02, 2, "stop_hit", 0.008)
    ef.add_trade(b, 0.004, 1, "stop_hit", 0.008)  # gross win, net loss
    ef.merge_acc(a, b)
    s = ef.summarize(a)
    assert s["n"] == 3 and s["win_pct"] == round(100 / 3, 2)
    assert abs(s["pfnet"] - round(0.092 / (0.028 + 0.004), 4)) < 1e-9
    assert s["exit_reasons"]["stop_hit"]["n"] == 2


def test_shards_partition_universe_with_no_overlap():
    syms = [f"S{i}.NS" for i in range(103)]
    parts = [ef.shard_symbols(syms, k, 4) for k in range(4)]
    assert sorted(sum(parts, [])) == sorted(syms)


def test_process_symbol_with_injected_signals_and_merge_roundtrip(tmp_path):
    df = _df()
    accs = {}
    ef.process_symbol(df, accs, 0.008, sigfn=lambda d, key: [80, 150, 220] if key in ("gg_long", "gg_short") else [])
    assert accs and all(("gap_and_go" in t) for t in accs)
    assert any("__short__" in t for t in accs) and any("__long__" in t for t in accs)
    (tmp_path / "s0.json").write_text(json.dumps({"accs": accs, "symbols_processed": 1, "universe_total": 10}))
    (tmp_path / "s1.json").write_text(json.dumps({"accs": accs, "symbols_processed": 1, "universe_total": 10}))
    doc = ef.merge(str(tmp_path), str(tmp_path / "out" / "m.json"))
    t = next(iter(accs))
    assert doc["cells"][t]["n"] == 2 * accs[t]["n"] and doc["symbols_processed"] == 2


def test_real_collect_signals_runs_against_main_functions():
    """Smoke: the real main.py entry functions are callable through collect_signals without error."""
    df = _df(n=200)
    for key in ef.ENTRY_SETS:
        assert isinstance(ef.collect_signals(df, key), list)
