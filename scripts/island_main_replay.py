"""Island-reversal main.py-function replay (backlog B-881).

ENTRY and EXIT decisions are the REAL main.island_swing_entry_signal (live detector + filters + ATR 1.5 stop)
and main.brk20_min_rr_exit_reason (the exact function main._island_swing_exit_adapter wraps: gap-aware stop ->
EMA13 rule exit -> 30-bar max hold). Never a reimplementation. The driver only supplies the bar loop.
Live conventions: signal on the CLOSE of bar k, fill at that close (as _island_swing_try_entry), exits are
evaluated from bar k+1. Cost = main.ROUND_TRIP_COST_PCT/100 (0.8%). Universe = main._load_nse_universe_from_file()
(full, NOT main.NSE_FULL_UNIVERSE). LONG only: main has no island short port, so the short mirror is owed
(backlog), not faked.

Tag semantics (every tag in main.ISLAND_ALL_TAGS is its own row, never merged):
  *__v1            overlapping fills (research v1 cells: every signal opens an independent trade)
  *__nonovl__v2    strict FIFO (one position per symbol, re-entry allowed on the exit bar)
  *__segis__v2 / *__segoos__v2   the nonovl trades split by ENTRY bar vs SPLIT_FRAC (default 0.6) of each
                   symbol's own time span (or SPLIT_DATE), as in scripts/island_validation.py.
Chunks (CHUNK env, each tag in exactly one chunk): gap05 | v1 | segis | segoos | nonovl.

Modes (argv[1]):
  run    env: CHUNK, SHARD, NSHARDS, INTERVAL (1d), PERIOD (5y), SPLIT_DATE, SPLIT_FRAC, SYMBOL_LIMIT,
         SYNTHETIC=1 (offline smoke, NOT a result)  -> out/island_<chunk>_s<shard>.json (raw sums)
  merge  python3 scripts/island_main_replay.py merge DIR [OUT.json] -> per-tag metrics incl. exit reasons.
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

CHUNKS = ("gap05", "v1", "segis", "segoos", "nonovl")
MIN_BARS = 22
TRADING_HOURS_PER_1D_BAR = 6.25  # NSE 09:15-15:30


def chunk_of(tag: str) -> str:
    """Each tag belongs to exactly one chunk (priority order: gap05, v1, segis, segoos, nonovl)."""
    if "island_gap05" in tag:
        return "gap05"
    if tag.endswith("__v1"):
        return "v1"
    if "__segis__" in tag:
        return "segis"
    if "__segoos__" in tag:
        return "segoos"
    return "nonovl"


def tags_for_chunk(m, chunk):
    return [t for t in m.ISLAND_ALL_TAGS if chunk_of(t) == chunk]


def mode_of(tag):
    return "overlap" if tag.endswith("__v1") else ("is" if "__segis__" in tag else "oos" if "__segoos__" in tag else "fifo")


def collect_signals(m, df, tag):
    """{bar k: sig} from the REAL main.island_swing_entry_signal on every bar (cheap real-detector pre-gate)."""
    sigs = {}
    n = len(df)
    for k in range(MIN_BARS - 1, n - 1):
        sub = df.iloc[:k + 1]
        if not m.island_bottom_signal_on_last_bar(sub):  # superset gate (gap05 only tightens it)
            continue
        s = m.island_swing_entry_signal(sub, tag)
        if s:
            sigs[k] = s
    return sigs


def run_trade(m, df, k, sig, dates, cost):
    """Fill at signal close; exits from bar k+1 via the real exit fn. Returns (trade, exit_bar)."""
    n = len(df)
    ep, stop0 = sig["entry_price"], sig["stop_loss"]
    fill_day = dates[k + 1]
    for j in range(k + 1, n):
        reason, px = m.brk20_min_rr_exit_reason(df.iloc[:j + 1], fill_day, ep, stop0, "long")
        if reason:
            g = (px - ep) / ep
            return {"gross": g, "net": g - cost, "held": j - k, "reason": "island_" + reason, "entry_i": k + 1}, j
    g = (float(df["Close"].iloc[-1]) - ep) / ep
    return {"gross": g, "net": g - cost, "held": n - 1 - k, "reason": "data_end_forced_close", "entry_i": k + 1}, n - 1


def replay_symbol(m, df, tags, cost, split_ts=None):
    """{tag: [trades]} for one symbol. Signals are computed once per filter variant (via its first tag)."""
    df = df.reset_index(drop=True)
    if len(df) < MIN_BARS + 3:
        return {t: [] for t in tags}
    dates = df["Date"].astype(str).to_numpy()
    idx = pd.to_datetime(dates)
    sig_cache, fifo_cache, out = {}, {}, {}
    for tag in tags:
        flt = m._ISLAND_FILTER_OF_TAG[tag]
        if flt not in sig_cache:
            sig_cache[flt] = collect_signals(m, df, tag)
        sigs = sig_cache[flt]
        mode = mode_of(tag)
        trades = []
        if mode == "overlap":
            for k, s in sorted(sigs.items()):
                trades.append(run_trade(m, df, k, s, dates, cost)[0])
        else:
            if flt not in fifo_cache:
                lst, free = [], 0
                for k, s in sorted(sigs.items()):
                    if k < free:
                        continue
                    tr, free = run_trade(m, df, k, s, dates, cost)
                    lst.append(tr)
                fifo_cache[flt] = lst
            trades = fifo_cache[flt]
            if mode in ("is", "oos"):
                ts = split_ts(idx)
                trades = [t for t in trades
                          if (idx[min(t["entry_i"], len(idx) - 1)] < ts) == (mode == "is")]
        out[tag] = trades
    return out


def make_split_ts(split_date, split_frac):
    def f(idx):
        if split_date:
            return pd.Timestamp(split_date)
        return idx[0] + (idx[-1] - idx[0]) * float(split_frac)
    return f


def synthetic_frame(seed, n=900):
    """Synthetic OHLC with injected gap-down / gap-up island bottoms so the real detector fires."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.015, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.003, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    for i in range(60, n - 12, 45):  # island: gap down at i, gap up reclaim at i+2
        lo[i] = lo[i - 1] * 0.93
        hi[i] = lo[i - 1] * 0.97
        o[i], c[i] = hi[i] * 0.99, lo[i] * 1.01
        lo[i + 1] = hi[i] * 0.995
        hi[i + 1] = lo[i + 1] * 1.01
        c[i + 1] = o[i + 1] = (lo[i + 1] + hi[i + 1]) / 2
        lo[i + 2] = hi[i + 1] * 1.03
        hi[i + 2] = lo[i + 2] * 1.04
        o[i + 2], c[i + 2] = lo[i + 2] * 1.005, hi[i + 2] * 0.995
    v = rng.integers(2e6, 9e6, n).astype(float)
    d = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c, "Volume": v})


def load_frames(m, interval, period, shard, nshards, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        return {f"SYN{k}": synthetic_frame(k) for k in range(limit or 3)}
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
    chunk = os.environ.get("CHUNK", "nonovl")
    interval = os.environ.get("INTERVAL", "1d")
    period = os.environ.get("PERIOD", "5y")
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    split_ts = make_split_ts(os.environ.get("SPLIT_DATE", ""), float(os.environ.get("SPLIT_FRAC") or 0.6))
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = tags_for_chunk(m, chunk)
    frames = load_frames(m, interval, period, shard, nshards, limit)
    aggs = {t: br.agg_new() for t in tags}
    for sym, df in frames.items():
        try:
            res = replay_symbol(m, df, tags, cost, split_ts)
        except Exception as ex:
            print("ERROR", sym, ex)
            continue
        for t, trs in res.items():
            br.agg_add(aggs[t], trs)
    out = {"chunk": chunk, "interval": interval, "period": period, "shard": shard, "nshards": nshards,
           "n_symbols": len(frames), "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT, "atr_mult": m.ISLAND_ATR_MULT,
           "synthetic": os.environ.get("SYNTHETIC") == "1", "direction": "long",
           "short_mirror": "owed: main.py has no island short port",
           "cells": {t: {"mode": mode_of(t), "raw": a} for t, a in aggs.items()}}
    os.makedirs("out", exist_ok=True)
    path = f"out/island_{chunk}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for t, a in aggs.items():
        mt = br.agg_metrics(a)
        print(t, "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"], "hold", mt["avg_held_bars"])
    print("wrote", path)


def _with_hours(mt):
    mt = dict(mt)
    mt["avg_held_hours"] = round(mt["avg_held_bars"] * TRADING_HOURS_PER_1D_BAR, 1)
    return mt


def merge(d, out_path=None):
    tags, meta = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "island_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        for t, c in r["cells"].items():
            e = tags.setdefault(t, {"mode": c["mode"], "agg": br.agg_new(), "n_symbols": 0, "shards": 0,
                                    "chunk": r["chunk"]})
            br.agg_merge(e["agg"], c["raw"])
            e["n_symbols"] += r["n_symbols"]
            e["shards"] += 1
        meta = {k: r[k] for k in ("interval", "period", "cost_round_trip_pct", "atr_mult", "synthetic",
                                  "direction", "short_mirror")}
    rows = [{"tag": t, "chunk": e["chunk"], "mode": e["mode"], "n_symbols": e["n_symbols"], "shards": e["shards"],
             "metrics": _with_hours(br.agg_metrics(e["agg"]))} for t, e in sorted(tags.items())]
    out = {**meta, "note": "avg_held_hours = avg_held_bars x 6.25 trading hours (1d bars)", "rows": rows}
    json.dump(out, open(out_path or os.path.join(d, "island_all.json"), "w"), indent=1)
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
