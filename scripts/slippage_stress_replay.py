"""B-422 empirical slippage-stress + liquidity-filter replay over the top viable swing tags (REAL main.py code).

The analytic screen (scripts/slippage_stress_viable.py -> docs/SLIPPAGE_STRESS_VIABLE.md) is algebra on registry
numbers; this driver re-runs the strategies themselves:

  (a) cost stress: the cost model is overridden ON THE `main` MODULE (main.ROUND_TRIP_COST_PCT = cost_pct) before a
      cell's replay, so every real main.py function that reads it sees the stressed value, and the per-trade net is
      gross - cost_pct/100 (same convention as the drivers reused below). Baseline 0.8% is always run as the control.
  (b) liquidity filter: an entry is dropped when the 20-day average traded value (mean Close x Volume over the 20 daily
      bars ENDING AT the signal bar, inclusive; entry is at that bar's close, so no look-ahead) is below
      min_turnover_cr crore (1 Cr = 1e7 INR). Fewer than 20 bars or missing volume = fails any threshold > 0.
      The filter sits INSIDE the bar loop (wraps the real entry fn), so a dropped entry frees the symbol for a later
      signal exactly as live would; it is never a post-hoc trade filter. Dropped signals are counted.

Strategies: the top TOP_N (default 10) registry tags by PFnet that are viable at read time (StrategyDef.is_viable())
AND have a main.py-calling replay here (REPLAYABLE), ties broken by shorter avg hold (faster-turnover rule). The
selection is recomputed from strategy_registry at plan time, never hardcoded. Drivers reused unchanged:
  classic    -> scripts/swing_classic_main_replay.replay_symbol (power_play, primary_base, gap_and_go, oneil cells)
  exitfamily -> scripts/gap_and_go_exitfamily_replay.replay_exitfamily (main.exitfamily_walk cells)
  b412       -> scripts/b412_replay.replay_be baseline (minervini_vcp entry + exit, no ratchet)
band_cap is off (the registered baseline convention); the rsbandfloor variants are not part of this pass.

Each (cost, turnover) cell is its own tag per the naming grammar (stress_tag): `cost<x>` and `turncr<y>` inserted
alphabetically into the params field (legacy tags get `__cost<x>_turncr<y>` appended). The (0.8, 0) cell is the
control (a reproduction of the registered tag in this run), also emitted under its explicit tag.

Speed: swing entry/exit fns do not read ROUND_TRIP_COST_PCT today, so gross trades are cost-invariant. This is
CHECKED, not assumed: the first CHECK_SYMBOLS symbols are replayed in full at every cost; if any gross/held/reason
sequence differs, the job switches to a full replay per cost for every symbol and says so (cost_invariant=false).

Universe = main._load_nse_universe_from_file() (full NSE, never NSE_FULL_UNIVERSE). Daily bars, 5y.
Modes: plan (env TOP_N, NSHARDS) -> matrix JSON; run (env TAG, SHARD, NSHARDS, COSTS, TURNOVERS, SYMBOL_LIMIT,
SYNTHETIC=1 smoke) -> out/sstress_<i>_s<shard>.json; merge <dir> [out] -> SUMMARY lines + RESULTS_JSON line +
`registration` list (one entry per stressed tag, every measured field kept) for later registry registration.
"""
import glob
import json
import math
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_COST_PCT = 0.8
DEFAULT_COSTS = (1.2, 1.6)
DEFAULT_TURNOVERS = (0.0, 1.0, 5.0)
TURNOVER_DAYS = 20
CRORE = 1e7
CHECK_SYMBOLS = 5

# registry name -> how to replay it with main.py code
REPLAYABLE = {
    "power_play_high_tight_flag": {"driver": "classic", "family": "power_play", "tag": "power_play"},
    "primary_base": {"driver": "classic", "family": "primary_base", "tag": "primary_base"},
    "gap_and_go_swing": {"driver": "classic", "family": "gap_and_go", "tag": "gap_and_go"},
    "minervini_vcp__swing__long__1d__benone__v1": {"driver": "b412", "strat": "minervini_long"},
    "order_block_delta__retest__long__1d__benone__v1": {"driver": "b412", "strat": "ob_long"},
    "volume_profile_poc__swing__long__1d__benone__v1": {"driver": "b412", "strat": "vp_long"},
    "gap_and_go__swing__long__1d__benone__v1": {"driver": "b412", "strat": "gap_long"},
}
ONEIL_TAGS = ("oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v2",
              "oneil_newhigh__first__long__1w__atr3_h26_rsnone__v2",
              "oneil_pivot__breakout__long__1w__atr3_chase10_h26_rsnone__v2")
EXITFAMILY_TAGS = ("gap_and_go__exitinval__long__1d__atr6d0_hold30_sigelder__v2",
                   "gap_and_go__exitexhaust__long__1d__atr2d5_hold30_trail6d0_xroc__v2",
                   "gap_and_go__exitinval__long__1d__atr6d0_hold30_sigema13w__v2",
                   "gap_and_go__exitexhaust__long__1d__atr2d5_hold30_trail6d0_xvolclimax__v2",
                   "gap_and_go__exitinval__long__1d__atr2d5_hold30_sigelder__v2")
for _t in ONEIL_TAGS:
    REPLAYABLE[_t] = {"driver": "classic", "family": "oneil", "tag": _t}
for _t in EXITFAMILY_TAGS:
    REPLAYABLE[_t] = {"driver": "exitfamily", "tag": _t}

ENTRY_FNS = ("power_play_entry_signal", "primary_base_entry_signal", "gap_and_go_entry_signal",
             "oneil_swing_entry_signal", "minervini_vcp_entry_signal", "order_block_entry_signal",
             "volume_profile_poc_entry_signal")


# ------------------------------------------------------------------ pure helpers (unit tested)
def fmt_num(x) -> str:
    """Naming grammar number: 1.2 -> '1d2', 0.8 -> '0d8', 5.0 -> '5', 0 -> '0', 0.5 -> '0d5'."""
    x = float(x)
    if x == int(x):
        return str(int(x))
    return f"{x:g}".replace(".", "d")


def stress_tag(base: str, cost_pct, min_turnover_cr) -> str:
    """A NEW tag for one (cost, turnover) cell, never a rename of `base`."""
    extra = [f"cost{fmt_num(cost_pct)}", f"turncr{fmt_num(min_turnover_cr)}"]
    parts = base.split("__")
    if len(parts) >= 6 and parts[-1].startswith("v"):
        toks = [t for t in parts[4].split("_") if t] + extra
        parts[4] = "_".join(sorted(toks))
        return "__".join(parts)
    return f"{base}__{'_'.join(extra)}"


def apply_cost_override(m, cost_pct):
    """Set the cost model on the main module; returns the previous value so callers can restore it."""
    prev = m.ROUND_TRIP_COST_PCT
    m.ROUND_TRIP_COST_PCT = float(cost_pct)
    return prev


def avg_turnover_cr(win, days=TURNOVER_DAYS) -> float:
    """Mean(Close x Volume) over the last `days` rows of win (signal bar inclusive), in crore. NaN if unknown."""
    if win is None or len(win) < days or "Volume" not in win.columns:
        return float("nan")
    tail = win.iloc[-days:]
    tv = tail["Close"].to_numpy(float) * tail["Volume"].to_numpy(float)
    if not np.isfinite(tv).all():
        return float("nan")
    return float(tv.mean() / CRORE)


def turnover_ok(win, min_cr) -> bool:
    if not min_cr or float(min_cr) <= 0:
        return True
    v = avg_turnover_cr(win)
    return math.isfinite(v) and v >= float(min_cr)


class FilteredMain:
    """Proxy over the real main module: every attribute is main's own, except the entry fns, which call the real
    fn and then drop the signal when the window fails the turnover filter (counted in .dropped)."""

    def __init__(self, m, min_cr):
        self._m = m
        self._min = float(min_cr or 0)
        self.dropped = 0
        for name in ENTRY_FNS:
            if hasattr(m, name):
                setattr(self, name, self._wrap(getattr(m, name)))

    def _wrap(self, fn):
        def w(win, *a, **k):
            sig = fn(win, *a, **k)
            if sig and not turnover_ok(win, self._min):
                self.dropped += 1
                return None
            return sig
        return w

    def __getattr__(self, name):
        return getattr(self._m, name)


def select_tags(registry, top_n=10):
    """Top-N viable registry entries that have a replay here, PFnet desc, then shorter hold."""
    rows = [s for s in registry if s.name in REPLAYABLE and s.is_viable() and s.metrics.pfnet is not None]
    rows.sort(key=lambda s: (-float(s.metrics.pfnet), float(s.metrics.avg_held_bars or 0)))
    return [s.name for s in rows[:top_n]]


def parse_list(s, default):
    if s is None or str(s).strip() == "":
        return list(default)
    return [float(x) for x in str(s).split(",") if x.strip()]


# ------------------------------------------------------------------ replay
def replay_one(proxy, df, spec, cost):
    if spec["driver"] == "classic":
        import swing_classic_main_replay as cl
        return cl.replay_symbol(proxy, df, spec["family"], spec["tag"], cost, "off")
    if spec["driver"] == "exitfamily":
        import gap_and_go_exitfamily_replay as gx
        return gx.replay_exitfamily(proxy, df, spec["tag"], cost, "off")
    import b412_replay as b4
    return b4.replay_be(b4.strat_spec(proxy, spec["strat"]), df.reset_index(drop=True), cost, None)


def _sig(trades):
    return [(round(t["gross"], 12), t["held"], t["reason"]) for t in trades]


def run():
    import brk20_replay as br
    import swing_classic_main_replay as cl
    import main as m
    tag = os.environ["TAG"]
    spec = REPLAYABLE[tag]
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    costs = [BASE_COST_PCT] + [c for c in parse_list(os.environ.get("COSTS"), DEFAULT_COSTS) if c != BASE_COST_PCT]
    turns = parse_list(os.environ.get("TURNOVERS"), DEFAULT_TURNOVERS)
    if 0.0 not in turns:
        turns = [0.0] + turns
    frames = cl.load_frames(m, shard, nshards, limit)
    aggs = {(c, t): br.agg_new() for c in costs for t in turns}
    dropped = {t: 0 for t in turns}
    invariant, checked = True, 0
    for sym, df in frames.items():
        df = df.reset_index(drop=True)
        for t in turns:
            proxy = FilteredMain(m, t)
            try:
                if invariant and checked >= CHECK_SYMBOLS:
                    apply_cost_override(m, BASE_COST_PCT)
                    base = replay_one(proxy, df, spec, BASE_COST_PCT / 100.0)
                    for c in costs:
                        br.agg_add(aggs[(c, t)], [{**x, "net": x["gross"] - c / 100.0} for x in base])
                else:
                    per = {}
                    for c in costs:
                        apply_cost_override(m, c)
                        per[c] = replay_one(FilteredMain(m, t) if c != costs[0] else proxy, df, spec, c / 100.0)
                        br.agg_add(aggs[(c, t)], per[c])
                    if len({json.dumps(_sig(v)) for v in per.values()}) > 1:
                        invariant = False
                        print("COST-DEPENDENT trades on", sym, "-> full replay per cost from here on")
            except Exception as ex:
                print("ERROR", sym, t, ex)
            finally:
                apply_cost_override(m, BASE_COST_PCT)
            dropped[t] += proxy.dropped
        checked += 1
    res = {"backlog": "B-422", "tag": tag, "spec": spec, "interval": cl.INTERVAL, "period": cl.PERIOD,
           "shard": shard, "nshards": nshards, "n_symbols": len(frames), "costs": costs, "turnovers": turns,
           "cost_invariant": invariant, "cost_check_symbols": min(checked, CHECK_SYMBOLS),
           "dropped_signals_by_turnover": {fmt_num(t): n for t, n in dropped.items()},
           "synthetic": os.environ.get("SYNTHETIC") == "1",
           "cells": [{"cost_pct": c, "min_turnover_cr": t, "raw": aggs[(c, t)]} for c in costs for t in turns]}
    od = os.environ.get("OUT_DIR") or "out"
    os.makedirs(od, exist_ok=True)
    idx = sorted(REPLAYABLE).index(tag)
    path = os.path.join(od, f"sstress_{idx:02d}_s{shard}.json")
    json.dump(res, open(path, "w"), indent=1)
    for cell in res["cells"]:
        mt = br.agg_metrics(cell["raw"])
        print(stress_tag(tag, cell["cost_pct"], cell["min_turnover_cr"]), "n", mt["n"], "pfnet", mt["pfnet"],
              "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)
    return res


def plan(env=None):
    e = os.environ if env is None else env
    import strategy_registry as sr
    ns = int(e.get("NSHARDS") or 2)
    tags = select_tags(sr.REGISTRY, int(e.get("TOP_N") or 10))
    return {"include": [{"tag": t, "shard": s, "nshards": ns} for t in tags for s in range(ns)]}


def merge(d, out_path=None):
    import brk20_replay as br
    import strategy_registry as sr
    reg = {s.name: s for s in sr.REGISTRY}
    pooled, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "sstress_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        e = meta.setdefault(r["tag"], {"n_symbols": 0, "cost_invariant": True, "dropped": {}, "synthetic": False})
        e["n_symbols"] += r["n_symbols"]
        e["cost_invariant"] = e["cost_invariant"] and r["cost_invariant"]
        e["synthetic"] = e["synthetic"] or r["synthetic"]
        for k, v in r["dropped_signals_by_turnover"].items():
            e["dropped"][k] = e["dropped"].get(k, 0) + v
        for c in r["cells"]:
            br.agg_merge(pooled.setdefault((r["tag"], c["cost_pct"], c["min_turnover_cr"]), br.agg_new()), c["raw"])
    run_id = os.environ.get("GITHUB_RUN_ID")
    rows, registration = [], []
    for (tag, c, t), a in sorted(pooled.items()):
        mt = br.agg_metrics(a)
        s = reg.get(tag)
        st = stress_tag(tag, c, t)
        rows.append({"base_tag": tag, "tag": st, "cost_pct": c, "min_turnover_cr": t,
                     "control": c == BASE_COST_PCT and t == 0, "registry_pfnet": s.metrics.pfnet if s else None,
                     "metrics": mt, **{k: meta[tag][k] for k in ("n_symbols", "cost_invariant", "synthetic")},
                     "dropped_signals": meta[tag]["dropped"].get(fmt_num(t), 0)})
        registration.append({
            "name": st, "base_tag": tag, "categories": list(s.categories) if s else [],
            "pfnet": mt["pfnet"], "pfgross": mt["pfgross"], "win_rate_pct": mt["win_pct"], "n_trades": mt["n"],
            "avg_held_bars": mt["avg_held_bars"], "avg_net_pct": mt["avg_net_pct"], "exit_reasons": mt["exit_reasons"],
            "cost_round_trip_pct": c, "min_turnover_cr": t, "universe": f"full_nse ({meta[tag]['n_symbols']} loaded)",
            "run_ref": f"slippage-stress-replay.yml run {run_id}", "source": f"scripts/slippage_stress_replay.py "
            f"({REPLAYABLE[tag]['driver']} driver, real main.py entry/exit fns, cost override on main module)"})
    res = {"backlog": "B-422", "run_id": run_id, "universe": "main._load_nse_universe_from_file() (full NSE)",
           "rows": rows, "registration": registration}
    json.dump(res, open(out_path or os.path.join(d, "slippage_stress_all.json"), "w"), indent=1)
    print("SUMMARY tag | cost% | min turnover Cr | n | win% | PFnet | PFgross | hold | dropped | registry PFnet")
    for r in rows:
        mt = r["metrics"]
        print(f"{r['tag']} | {r['cost_pct']} | {r['min_turnover_cr']} | {mt['n']} | {mt['win_pct']} | {mt['pfnet']}"
              f" | {mt['pfgross']} | {mt['avg_held_bars']} | {r['dropped_signals']} | {r['registry_pfnet']}"
              f"{' (CONTROL)' if r['control'] else ''}")
    print("RESULTS_JSON: " + json.dumps(res, separators=(",", ":")))
    return res


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
