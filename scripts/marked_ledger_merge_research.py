#!/usr/bin/env python3
"""B-743 merge driver: collect_N.json (written by `portfolio_overlay_research.py collect --marks`) ->
simulate_marked_ledger per stream key (<base>|<long|short>|<atr_mult>). Research only, no live wiring.

Each row prints the stream's standalone stats (PFnet net/gross, win %, n, avg hold, exit breakdown, from
portfolio_overlay_research.stats) next to the Vince-rule ledger outcome (final equity, max DD, closes by reason,
refused stopless trades). Dates are epoch seconds; the date axis is every entry/exit/mark second seen."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portfolio_ledger_research as L  # noqa: E402
import portfolio_overlay_research as P  # noqa: E402


def load_shards(path):
    streams, paths, fetched, universe = {}, {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "collect_*.json"), recursive=True)):
        d = json.load(open(f))
        fetched += d.get("fetched", 0)
        universe += d.get("universe", 0)
        for k, v in d["streams"].items():
            streams.setdefault(k, []).extend(v)
        for k, v in (d.get("paths") or {}).items():
            paths.setdefault(k, []).extend(v)
    return streams, paths, fetched, universe


def merge_marked(path, json_out=None, max_open=10):
    streams, paths, fetched, universe = load_shards(path)
    if not paths:
        raise SystemExit("no `paths` in collect files: rerun collect with --marks")
    rows = []
    for key in sorted(streams):
        if key not in paths or len(paths[key]) != len(streams[key]):
            continue
        trades = L.ledger_trades_from_collect(streams, paths, key)
        dates = sorted({t["entry_date"] for t in trades} | {t["exit_date"] for t in trades}
                       | {d for t in trades for d in t["marks"]})
        res = L.simulate_marked_ledger(trades, dates, max_open=max_open)
        by_reason = {}
        for c in res["closes"]:
            by_reason[c[3]] = by_reason.get(c[3], 0) + 1
        base, direction, am = key.split("|")
        rows.append({"key": key, "base": base, "dir": direction, "atr_mult": am, "stats": P.stats(streams[key]),
                     "ledger": {"final_equity": res["final_equity"], "max_dd_pct": res["max_dd_pct"],
                                "n_closed": res["n_closed"], "n_refused": res["n_refused"],
                                "closes_by_reason": dict(sorted(by_reason.items()))}})
    out = {"fetched": fetched, "universe": universe, "max_open": max_open, "rows": rows}
    for r in rows:
        s, lg = r["stats"], r["ledger"]
        print(f"{r['key']:40s} n={s['n']} PFnet={s['pfnet']} gross={s['pf_gross']} win%={s['win_pct']} "
              f"hold={s['avg_hold_bars']} | ledger eq={lg['final_equity']} dd%={lg['max_dd_pct']} "
              f"closed={lg['n_closed']} refused={lg['n_refused']} {lg['closes_by_reason']} exits={s.get('exit_reasons')}")
    if json_out:
        json.dump(out, open(json_out, "w"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--json")
    ap.add_argument("--max-open", type=int, default=10)
    a = ap.parse_args(argv)
    merge_marked(a.dir, a.json, a.max_open)


if __name__ == "__main__":
    main()
