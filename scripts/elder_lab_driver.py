#!/usr/bin/env python3
"""Shared shard/merge driver for the Elder stop-offset, pyramiding and signal-invalidation
harnesses (B-606, B-742/B-743, B-740). Research only; no main.py edits.

Full universe via main._load_nse_universe_from_file(); every shard emits per-tag aggregates
(n, wins, net and gross sums, hold, exit-reason counts, extras) into a small JSON artifact and
the merge stage prints PFnet net+gross, win %, n, avg hold, avg net return and exit breakdown,
plus the universe size (CLAUDE.md: keep every measured field).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402


def new_agg(extra=()):
    g = er.new_agg()
    g.update({k: 0.0 for k in extra})
    return g


def merge_aggs(a, b, extra=()):
    er.merge_aggs(a, b)
    for k in extra:
        a[k] = a.get(k, 0.0) + b.get(k, 0.0)
    return a


def merge_dir(path, extra=()):
    merged, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        universe += d.get("universe", 0)
        for tag, ag in d["aggs"].items():
            merge_aggs(merged.setdefault(tag, new_agg(extra)), ag, extra)
    rows = []
    for t, a in merged.items():
        r = {"tag": t, **er.summarize(a)}
        for k in extra:
            r[k] = int(a.get(k, 0))
        rows.append(r)
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "universe_size": universe,
            "cost_round_trip": er.COST_ROUND_TRIP, "rows": rows}


def print_table(res):
    print(f"universe symbols: {res['universe_size']}  fetched with data: {res['symbols_fetched']}  "
          f"round-trip cost: {res['cost_round_trip']}")
    print(f"{'tag':100s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}  exits")
    for r in res["rows"]:
        print(f"{r['tag']:100s} {r['n']:7d} {str(r['pfnet']):>7s} {str(r['pf_gross']):>8s} "
              f"{r['win_pct']:6.1f} {r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")


def run(argv, families, run_symbol, extra=()):
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=families)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        res = merge_dir(args.merge, extra)
        print_table(res)
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    if not args.family:
        ap.error("--family or --merge required")
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            fetched += 1
            run_symbol(er.prep(raw), args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched,
               "universe": len(syms), "aggs": aggs},
              open(os.path.join(args.out, f"{args.family}_{args.shard}.json"), "w"))
    return 0
