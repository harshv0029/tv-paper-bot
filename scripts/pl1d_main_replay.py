"""B-983: pattern-lab 1d LONG cells (starc fade full-universe, gap runaway) main.py-function replay.

ENTRY and EXIT decisions are the REAL main functions: main.pl1d_long_entry_signal(df, tag) and
main.pl1d_exit_reason(df, entry_day, stop, hold) (the function main._pl1d_exit_adapter wraps), tags = main.PL1D_CELLS.
Live convention: signal on the CLOSE of bar k, fill at that close, exits evaluated from bar k+1 (entry_day = date of
bar k). Strict FIFO per symbol per tag. Cost = main.ROUND_TRIP_COST_PCT/100. Universe =
main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE). LONG only here (short mirror = own tag family).

  run    env: SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result) -> out/pl1d_s<shard>.json
  merge  python3 scripts/pl1d_main_replay.py merge DIR [OUT.json] -> rows[].metrics, the schema
         main._replay_verified_tags() reads (docs/backtest_data/*main_replay_run_*.json).
"""
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brk20_replay as br  # noqa: E402
import bar_hygiene as bh  # noqa: E402
import chan_shape_macddiv_main_replay as base  # noqa: E402

MIN_BARS = 60
HOURS_PER_BAR = 6.25
INTERVAL = ("1d", "5y")


def pl1d_trade(m, df, k, sig, tag, dates, cost):
    n = len(df)
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    hold = m.PL1D_CELLS[tag][2]
    for j in range(k + 1, n):
        reason, px = m.pl1d_exit_reason(df.iloc[:j + 1], dates[k], stop0, hold)
        if reason:
            return base._trade(ep, px, j - k, reason, cost, k + 1, j)
    return base._trade(ep, float(df["Close"].iloc[-1]), n - 1 - k, "data_end_forced_close", cost, k + 1, n - 1)


def replay_symbol(m, df, tags, cost):
    df = df.reset_index(drop=True)
    n = len(df)
    out = {t: [] for t in tags}
    if n < MIN_BARS + 3:
        return out
    dates = df["Date"].astype(str).to_numpy()
    free = {t: 0 for t in tags}
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        for tag in tags:
            if k < free[tag]:
                continue
            sig = m.pl1d_long_entry_signal(sub, tag)
            if not sig:
                continue
            tr = pl1d_trade(m, df, k, sig, tag, dates, cost)
            out[tag].append(tr)
            free[tag] = tr["exit_i"] + 1
    return out


def run():
    import main as m
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = list(m.PL1D_CELLS)
    frames, dropped = bh.clean_frames(base.load_frames(m, "chan_shape", shard, nshards, limit))  # B-1110 glitch-bar cleaning  # 1d / 5y loader, full universe
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"family": "pl1d", "interval": INTERVAL[0], "period": INTERVAL[1], "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "bars_dropped_glitch": dropped, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "short_mirror": "owed: registered as its own tag family, not run here",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/pl1d_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d, out_path=None):
    tags = {}
    meta = {}
    dropped = 0
    for f in sorted(glob.glob(os.path.join(d, "**", "*_s*.json"), recursive=True)):
        r = json.load(open(f))
        if "cells" not in r:
            continue
        dropped += r.get("bars_dropped_glitch", 0)
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"agg": br.agg_new(), "n_symbols": 0, "shards": 0})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction",
                                  "short_mirror")}
    rows = []
    for t, e in sorted(tags.items()):
        mt = br.agg_metrics(e["agg"])
        mt["avg_held_hours"] = round(mt["avg_held_bars"] * HOURS_PER_BAR, 1)
        rows.append({"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": mt})
    out = {**meta, "bars_dropped_glitch": dropped, "note": "avg_held_hours = avg_held_bars x 6.25; schema read by main._replay_verified_tags", "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_h", mt["avg_held_hours"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
