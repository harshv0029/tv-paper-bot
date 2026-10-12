#!/usr/bin/env python3
"""macddiv 1h LONG cells re-run with strictly NON-OVERLAPPING trades (backlog B-812; same method as B-807 chan).

Cells (all long, 1h, from run 38188472624, PFnet >= 1.1): line_any atr3_w5, atr2_w5, atr1d5_w5; hist_any atr3_w5.
Method: for every symbol and cell, evaluate the trade EACH signal bar would open on its own (independent, via the
unchanged macd_divergence_research signal + elder_indicators_research.simulate, 0.8% round trip, ATR stop on every
trade), then apply a strict FIFO filter: keep a trade only if its entry bar is after the exit bar of the last kept
trade (one position per symbol per cell). FULL universe via main._load_nse_universe_from_file().
Tags: <old tag minus __v1>__nonovl__v2 (old tags untouched); B-814 adds IS/OOS split tags
<old minus __v1>_nonovl_segis__v2 / _segoos__v2 (split_date input, else split_frac of the time span; entry-bar based).
Note: er.simulate itself already skips signals before its previous exit (free = j), so the original run may already
have been non-overlapping; this harness checks that independently instead of assuming it (raw vs kept counts printed).
Usage:
  python3 scripts/macddiv_nonoverlap.py --shard 0 --nshards 8 --out out/
  python3 scripts/macddiv_nonoverlap.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import macd_divergence_research as md  # noqa: E402

INTERVAL = "1h"  # default; --interval overrides (1d/1h/15m/5m)
PERIODS = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}  # yfinance limits
# (variant, pivot half-width w, atr multiple)
CELLS = (("line_any", 5, 3.0), ("line_any", 5, 2.0), ("line_any", 5, 1.5), ("hist_any", 5, 3.0))
# "sweep": full IS/OOS grid, variants x pivot width x ATR (every cell its own tag, both directions)
SWEEP_CELLS = tuple((v, w, a) for v in ("line_any", "hist_any", "hist_zero") for w in (3, 5) for a in (1.5, 2.0, 3.0))
CELL_SETS = {"orig": CELLS, "sweep": SWEEP_CELLS}


def nonovl_tag(old):
    base = old[:-4] if old.endswith("__v1") else old
    return base + "__nonovl__v2"


def fifo_filter(trades):
    """trades: dicts with entry_i, exit_i. Strict FIFO: keep if entry_i > last kept exit_i."""
    kept, last_exit = [], -1
    for t in sorted(trades, key=lambda t: (t["entry_i"], t["exit_i"])):
        if t["entry_i"] > last_exit:
            kept.append(t)
            last_exit = t["exit_i"]
    return kept


def split_ts(idx, split_date="", split_frac=0.6):
    """IS/OOS boundary: explicit split_date if given, else the point split_frac of the way through the
    symbol's own [first, last] time span. A trade is IN-sample if its ENTRY bar is before the boundary."""
    if split_date:
        ts = pd.Timestamp(split_date)
        if getattr(idx, "tz", None) is not None and ts.tzinfo is None:
            ts = ts.tz_localize(idx.tz)
        return ts
    return idx[0] + (idx[-1] - idx[0]) * float(split_frac)


def segment_trades(trades, idx, ts):
    """Split trades (with entry_i) into (in_sample, out_of_sample) by entry bar timestamp vs ts."""
    ins, oos = [], []
    for t in trades:
        (ins if idx[min(t["entry_i"], len(idx) - 1)] < ts else oos).append(t)
    return ins, oos


def seg_tag(old, seg):
    """<old minus __v1>_nonovl_segis__v2 / _segoos__v2 (macddiv B-814 spec)."""
    base = old[:-4] if old.endswith("__v1") else old
    return f"{base}_nonovl_seg{seg}__v2"


def has_overlap(trades):
    ts = sorted(trades, key=lambda t: t["entry_i"])
    return any(b["entry_i"] <= a["exit_i"] for a, b in zip(ts, ts[1:]))


def independent_trades(df, sig, direction, atr_mult):
    """One independent trade per signal bar (er.simulate restricted to that single signal)."""
    out = []
    for s in np.flatnonzero(sig[direction]):
        one = dict(sig)
        mask = np.zeros(len(df), bool)
        mask[s] = True
        one[direction] = mask
        tr = er.simulate(df, one, direction, atr_mult, {})
        if tr:
            e = int(s) + 1
            out.append({**tr[0], "entry_i": e, "exit_i": e + tr[0]["hold"] - 1})
    return out


def cell_trades(df, sig, direction, atr_mult):
    """(kept non-overlapping trades, count of independent signal trades before the filter)."""
    raw = independent_trades(df, sig, direction, atr_mult)
    return fifo_filter(raw), len(raw)


def run_symbol(df, aggs, raw_counts=None, split_date="", split_frac=0.6, interval=None, cells=None,
               directions=("long",)):
    interval = interval or INTERVAL
    cells = CELLS if cells is None else cells
    specs = {(v, p["w"]): f for v, p, f in md.variant_specs()}
    ts = split_ts(df.index, split_date, split_frac)
    for variant, w, am in cells:
        sig = specs[(variant, w)](df)
        for direction in directions:
            if not sig[direction].any():
                continue
            kept, nraw = cell_trades(df, sig, direction, am)
            base_tag = er.make_tag(md.FAMILY, variant, direction, interval, {"w": w, "atr": am})
            tag = nonovl_tag(base_tag)
            er.add_trades(aggs.setdefault(tag, er.new_agg()), kept)
            ins, oos = segment_trades(kept, df.index, ts)
            er.add_trades(aggs.setdefault(seg_tag(base_tag, "is"), er.new_agg()), ins)
            er.add_trades(aggs.setdefault(seg_tag(base_tag, "oos"), er.new_agg()), oos)
            if raw_counts is not None:
                raw_counts[tag] = raw_counts.get(tag, 0) + nraw


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    interval = args.interval
    cells = CELL_SETS[args.cells]
    directions = tuple(d for d in args.directions.split(",") if d)
    aggs, raw_counts, fetched = {}, {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period or PERIODS[interval], interval)
            if raw is None or len(raw) < 120:
                continue
            run_symbol(er.prep(raw), aggs, raw_counts, args.split_date, args.split_frac, interval, cells, directions)
            fetched += 1
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"shard {args.shard} {interval}: fetched {fetched}/{len(syms)}, tags {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"macddiv_nonovl_{interval}_{args.shard}.json"), "w") as f:
        json.dump({"interval": interval, "cells": args.cells, "directions": list(directions), "fetched": fetched, "universe": len(syms),
                   "raw_signal_trades": raw_counts, "split_date": args.split_date,
                   "split_frac": args.split_frac, "aggs": aggs}, f)


def merge_dir(path):
    merged, raw, fetched = {}, {}, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "macddiv_nonovl_*.json"), recursive=True)):
        with open(f) as fh:
            d = json.load(fh)
        fetched += d["fetched"]
        for t, n in d.get("raw_signal_trades", {}).items():
            raw[t] = raw.get(t, 0) + n
        for t, a in d["aggs"].items():
            er.merge_aggs(merged.setdefault(t, er.new_agg()), a)
    res = {t: {**er.summarize(a), "raw_signal_trades_before_fifo": raw.get(t)} for t, a in merged.items()}
    return {"method": "strict FIFO, one position per symbol per cell", "fetched": fetched, "results": res}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=8)
    ap.add_argument("--interval", default=INTERVAL, choices=sorted(PERIODS))
    ap.add_argument("--cells", default="orig", choices=sorted(CELL_SETS))
    ap.add_argument("--directions", default="long", help="comma list: long,short")
    ap.add_argument("--period", default="", help="blank = yfinance max for the interval")
    ap.add_argument("--split_date", default="", help="IS/OOS boundary (entry date < it = IS); blank = split_frac")
    ap.add_argument("--split_frac", type=float, default=0.6)
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        out = merge_dir(args.merge)
        if args.json:
            with open(args.json, "w") as f:
                json.dump(out, f, separators=(",", ":"))
        for t, m in sorted(out["results"].items(), key=lambda x: -(x[1]["pfnet"] or 0)):
            print(t, m["pfnet"], m["pf_gross"], m["win_pct"], m["n"], m["avg_hold_bars"],
                  m["raw_signal_trades_before_fifo"], m["exit_reasons"])
        return 0
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
