"""B-1160: envelope 5% fade 1h, BOTH directions, 12 cells: full-universe replay that CALLS the real main.py functions.

ENTRY / EXIT are main.envelope_fade_entry_signal(df, tag) and main.envelope_fade_exit_reason(df, direction, entry_pos,
stop, hold) over main.ENVELOPE_1H_CELLS (long AND short, ATR 2.5/4/6 x hold 18/30; every cell has an ATR14 stop, atrnone
cells are not ported). Universe = main._load_nse_universe_from_file() (full, NOT main.NSE_FULL_UNIVERSE). Cost =
main.ROUND_TRIP_COST_PCT/100 (0.8%). Live convention (as the pl1d port): signal on the CLOSE of bar k, fill at that close,
exits evaluated from bar k+1, strict FIFO per symbol per tag. Glitch bars cleaned with scripts/bar_hygiene.py (count written
to the output). DATA LIMIT: yfinance 1h history is capped at 730 days, so the sample is ~2 years, not 5; bar counts are
hourly bars (30 bars ~ 4-5 sessions), stated in the output. A numpy pre-filter (close vs SMA21 +/-5%) skips bars where the
real rule cannot fire (it is the rule's first test), so the real main.py function runs only on candidate bars.
Tags emitted are the registry grammar tags (`envelope__0d05_fade__<dir>__1h__atr<k>_h<N>__v1`); they carry ALL raw metrics
(pfnet net and gross, win %, n, avg hold bars, exit-reason breakdown). Validation only: wires nothing, no kill switch.

  run    env: SHARD, NSHARDS, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result) -> out/envelope_s<shard>.json
  merge  python3 scripts/envelope_main_replay.py merge DIR [OUT.json]
         (commit as docs/backtest_data/envelope_main_replay_run_<run id>.json)
"""
import glob
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_hygiene as bh  # noqa: E402
import brk20_replay as br  # noqa: E402
import chan_shape_macddiv_main_replay as base  # noqa: E402

MIN_BARS = 60
INTERVAL = ("1h", "730d")


def _candidates(df):
    """Bar indices where the envelope rule can fire in either direction (exact pre-filter, same SMA21 +/-5%)."""
    c = df["Close"].to_numpy(float)
    n = len(c)
    out = np.zeros(n, bool)
    if n < 22:
        return out
    cs = np.cumsum(np.r_[0.0, c])
    sma = np.full(n, np.nan)
    sma[20:] = (cs[21:] - cs[:n - 20]) / 21.0
    with np.errstate(invalid="ignore"):
        out = (c < sma * 0.95) | (c > sma * 1.05)
    return out


def _trade(ep, xp, held, reason, cost, entry_i, exit_i, sgn):
    g = sgn * (xp - ep) / ep
    return {"gross": g, "net": g - cost, "held": held, "reason": reason, "entry_i": entry_i, "exit_i": exit_i}


def envelope_trade(m, df, k, sig, tag, cost):
    n = len(df)
    direction, _kmult, hold = m.ENVELOPE_1H_CELLS[tag]
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    sgn = 1.0 if direction == "long" else -1.0
    for j in range(k + 1, n):
        res = m.envelope_fade_exit_reason(df.iloc[:j + 1], direction, k, stop0, hold)
        if res:
            return _trade(ep, res[1], j - k, res[0], cost, k + 1, j, sgn)
    return _trade(ep, float(df["Close"].iloc[-1]), n - 1 - k, "data_end_forced_close", cost, k + 1, n - 1, sgn)


def replay_symbol(m, df, tags, cost):
    df = df.reset_index(drop=True)
    n = len(df)
    out = {t: [] for t in tags}
    if n < MIN_BARS + 3:
        return out
    cand = _candidates(df)
    free = {t: 0 for t in tags}
    for k in np.flatnonzero(cand[:n - 1]):
        k = int(k)
        if k < MIN_BARS - 1:
            continue
        sub = df.iloc[:k + 1]
        for tag in tags:
            if k < free[tag]:
                continue
            sig = m.envelope_fade_entry_signal(sub, tag)
            if not sig:
                continue
            tr = envelope_trade(m, df, k, sig, tag, cost)
            out[tag].append(tr)
            free[tag] = tr["exit_i"] + 1
    return out


def run():
    import main as m
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = list(m.ENVELOPE_1H_CELLS)
    frames, dropped = bh.clean_frames(base.load_frames(m, "macddiv", shard, nshards, limit))  # 1h / 730d loader
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"family": "envelope", "interval": INTERVAL[0], "period": INTERVAL[1], "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "bars_dropped_glitch": dropped, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "both",
           "note": "yfinance 1h capped at 730d; hold/bar constants are HOURLY bars",
           "cells": {t: {"raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/envelope_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def merge(d, out_path=None):
    tags, meta, dropped = {}, {}, 0
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
        meta = {k: r[k] for k in ("family", "interval", "period", "cost_round_trip_pct", "synthetic", "direction", "note")}
    rows = []
    for t, e in sorted(tags.items()):
        rows.append({"tag": t, "n_symbols": e["n_symbols"], "shards": e["shards"], "metrics": br.agg_metrics(e["agg"])})
    out = {**meta, "bars_dropped_glitch": dropped, "rows": rows,
           "note2": "avg_held_bars are 1h bars; schema read by main._replay_verified_tags"}
    json.dump(out, open(out_path or os.path.join(d, "replay_all.json"), "w"), indent=1)
    for r in rows:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "hold_bars", mt["avg_held_bars"], mt["exit_reasons"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run()
