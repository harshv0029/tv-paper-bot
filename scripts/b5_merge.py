"""Shared shard-merge + full-table printer for the B-5xx research harnesses.

Emits EVERY measured field per tag (n, PFnet net, PFnet gross, win %, avg hold, avg net return,
exit-reason breakdown) plus the universe size, so nothing has to be recovered from artifacts
(CLAUDE.md: keep all backtest data intact; viability is derived at read time).
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402


def merge_dir(path):
    merged, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        universe += d.get("universe", 0)
        for tag, ag in d["aggs"].items():
            er.merge_aggs(merged.setdefault(tag, er.new_agg()), ag)
    rows = [{"tag": t, **er.summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "universe_size": universe,
            "cost_round_trip": er.COST_ROUND_TRIP, "rows": rows}


def print_table(res):
    print(f"universe symbols: {res['universe_size']}  fetched with data: {res['symbols_fetched']}  "
          f"round-trip cost: {res['cost_round_trip']}")
    print(f"{'tag':96s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}  exits")
    for r in res["rows"]:
        print(f"{r['tag']:96s} {r['n']:7d} {str(r['pfnet']):>7s} {str(r['pf_gross']):>8s} "
              f"{r['win_pct']:6.1f} {r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")


def merge_main(path, json_out=None):
    res = merge_dir(path)
    print_table(res)
    if json_out:
        json.dump(res, open(json_out, "w"), indent=1)
    return 0
