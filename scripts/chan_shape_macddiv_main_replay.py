"""chan_shape LONG 1d + macddiv LONG 1h main.py-function replay (backlog B-965).

ENTRY and EXIT decisions are the REAL main functions, never a reimplementation:
  chan_shape : main.chan_shape_long_entry_signal(df, tag) + main.chan_shape_exit_reason(df, entry_day, stop, hold)
               (the function main._chan_shape_exit_adapter wraps), tags = main.CHAN_SHAPE_CELLS (6 pooled nonovl cells).
  macddiv    : main.macddiv_long_cell_signal(df, tag) + main.macddiv_long_exit_reason(df, fill_i, stop),
               tags = main.MACDDIV_LONG_CELLS (4 pooled nonovl cells; main.macd_divergence_long_entry_signal inside).
The driver only supplies the bar loop. Live convention (chan_shape): signal on the CLOSE of bar k, fill at that close,
exits evaluated from bar k+1 (entry_day = date of bar k). macddiv: signal on the close of bar k, fill at the OPEN of bar
k+1 (as the research), stop from the signal. Strict FIFO per symbol per tag (a new entry only after the prior exit bar).
Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Universe = main._load_nse_universe_from_file() (full, NOT
main.NSE_FULL_UNIVERSE). LONG only here: the short mirror is a separate registered tag family (owed, backlog).

Modes (argv[1]):
  run    env: FAMILY (chan_shape|macddiv), SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result)
         -> out/<family>_s<shard>.json (raw sums)
  merge  python3 scripts/chan_shape_macddiv_main_replay.py merge DIR [OUT.json] -> rows[] with metrics (n, pfnet, ...)
         in the schema main._replay_verified_tags() reads (docs/backtest_data/*main_replay_run_*.json).
         Also prints ONE line `RESULTS_JSON: {...}` (compact, same schema) so the coordinator can copy the results from the
         job LOG into docs/backtest_data/<family>_main_replay_run_<run id>.json without downloading the artifact (B-1396a).
"""
import glob
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402  (exact-mergeable aggregation helpers)

MIN_BARS = 60
HOURS_PER_BAR = {"chan_shape": 6.25, "macddiv": 1.0}  # 1d bar = 6.25 market hours; 1h bar = 1
INTERVAL = {"chan_shape": ("1d", "5y"), "macddiv": ("1h", "730d")}


def tags_for(m, family):
    return list(m.CHAN_SHAPE_CELLS) if family == "chan_shape" else list(m.MACDDIV_LONG_CELLS)


def _trade(ep, xp, held, reason, cost, entry_i, exit_i):
    g = (xp - ep) / ep
    return {"gross": g, "net": g - cost, "held": held, "reason": reason, "entry_i": entry_i, "exit_i": exit_i}


def chan_shape_trade(m, df, k, sig, tag, dates, cost):
    n = len(df)
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    hold = m.CHAN_SHAPE_CELLS[tag][1]
    for j in range(k + 1, n):
        reason, px = m.chan_shape_exit_reason(df.iloc[:j + 1], dates[k], stop0, hold)
        if reason:
            return _trade(ep, px, j - k, reason, cost, k + 1, j)
    return _trade(ep, float(df["Close"].iloc[-1]), n - 1 - k, "data_end_forced_close", cost, k + 1, n - 1)


def replay_symbol(m, df, family, tags, cost):
    df = df.reset_index(drop=True)
    n = len(df)
    out = {t: [] for t in tags}
    if n < MIN_BARS + 3:
        return out
    dates = df["Date"].astype(str).to_numpy() if "Date" in df.columns else None
    free = {t: 0 for t in tags}
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        for tag in tags:
            if k < free[tag]:
                continue
            sig = m.chan_shape_long_entry_signal(sub, tag) if family == "chan_shape" else m.macddiv_long_cell_signal(sub, tag)
            if not sig:
                continue
            if family == "chan_shape":
                tr = chan_shape_trade(m, df, k, sig, tag, dates, cost)
            else:
                tr = macddiv_trade_full(m, df, k, sig, tag, cost)
                if tr is None:
                    continue
            out[tag].append(tr)
            free[tag] = tr["exit_i"] + 1
    return out


def macddiv_trade_full(m, df, k, sig, tag, cost):
    """Fill at the open of bar k+1; first exit event from the REAL macddiv_long_exit_reason; its exit bar index is found
    by walking the same function forward bar by bar (so held/exit_i are the real exit bar, not a guess)."""
    n = len(df)
    ep = float(df["Open"].iloc[k + 1])
    stop = ep - (sig["entry_price"] - sig["stop_loss"])
    if not (0 < stop < ep):
        return None
    fill = k + 1
    for j in range(fill, n):
        reason, px = m.macddiv_long_exit_reason(df.iloc[:j + 1], fill, stop)
        if reason:
            return _trade(ep, px, j - fill + 1, reason, cost, fill, j)
    return _trade(ep, float(df["Close"].iloc[-1]), n - fill, "data_end_forced_close", cost, fill, n - 1)


def synthetic_frame(seed, n=700):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.015, n)
    c = 100 * np.exp(np.cumsum(r) + 0.3 * np.sin(np.arange(n) / 25.0))
    o = c * (1 + rng.normal(0, 0.003, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                         "Volume": rng.integers(2e6, 9e6, n).astype(float)})


def load_frames(m, family, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 3)}
    interval, period = INTERVAL[family]
    syms = sorted(set(m._load_nse_universe_from_file()))[shard::nshards]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, period, interval)
        except Exception:
            continue
        if raw is None or len(raw) < MIN_BARS + 3:
            continue
        out[s] = raw.reset_index(drop=True)
    return out


def run():
    import main as m
    family = os.environ.get("FAMILY", "chan_shape")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = tags_for(m, family)
    frames = load_frames(m, family, shard, nshards, limit)
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, family, tags, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"family": family, "interval": INTERVAL[family][0], "period": INTERVAL[family][1], "shard": shard,
           "nshards": nshards, "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "short_mirror": "owed: registered as its own tag family, not run here",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/{family}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d, out_path=None):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "*_s*.json"), recursive=True)):
        r = json.load(open(f))
        if "cells" not in r:
            continue
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0, "family": r["family"]})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction",
                                  "short_mirror")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = br.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR[e["family"]], 1)
        rows.append({"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt})
    out = {**meta, "note": "avg_held_hours = avg_held_bars x market hours per bar; schema read by main._replay_verified_tags",
           "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    print(results_json_line(out))
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_h", mt["avg_held_hours"], mt["exit_reasons"])
    return out


WORKFLOW = {"chan_shape": ".github/workflows/chan-shape-main-replay.yml"}


def results_doc(out, run_id=None):
    """Compact docs/backtest_data row doc (main._replay_verified_tags schema) from merge() output. Keeps every measured
    field (n, pfnet, pfgross, win %, avg net/gross %, held bars/days/hours, exit-reason breakdown); avg_held_days =
    avg_held_bars x hours per bar / 6.25 (market hours per NSE day), so for 1d bars it equals avg_held_bars."""
    if run_id is None:
        rid = os.environ.get("GITHUB_RUN_ID")
        run_id = int(rid) if rid and rid.isdigit() else None
    fam = out.get("family", "")
    src = (f"{WORKFLOW.get(fam, 'chan_shape_macddiv_main_replay')} + scripts/chan_shape_macddiv_main_replay.py: "
           f"real main.py fns ({'chan_shape_long_entry_signal + chan_shape_exit_reason' if fam == 'chan_shape' else 'macddiv_long_cell_signal + macddiv_long_exit_reason'}), "
           "full universe main._load_nse_universe_from_file(), cost main.ROUND_TRIP_COST_PCT, strict FIFO per symbol per tag")
    rows = []
    for r in out.get("rows", []):
        mt = dict(r["metrics"])
        mt["avg_held_days"] = round(float(mt.get("avg_held_bars") or 0.0) * HOURS_PER_BAR.get(fam, 6.25) / 6.25, 2)
        rows.append({"tag": r["tag"], "n_symbols": r.get("n_symbols"), "shards": r.get("shards"), "metrics": mt})
    meta = {k: out[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction")
            if k in out}
    return {"run_id": run_id, "source": src, **meta, "rows": rows}


def results_json_line(out, run_id=None):
    return "RESULTS_JSON: " + json.dumps(results_doc(out, run_id), separators=(",", ":"), sort_keys=False)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
