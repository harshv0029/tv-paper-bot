#!/usr/bin/env python3
"""B-791: read the Minervini sweep artifact (docs/minervini_sweep_results_<uni>_<tf>.json, written by
scripts/minervini_sweep_lab.py) and print what the stored TSV could not: the confirmed universe size, the
exit-reason breakdown per cell, and PFnet per day held against the live minervini_vcp tag
(minervini_vcp__atrtrail__long__1d__atr1d5_h60__v1, PFnet 0.908). Research reading aid only.

Fetch the artifact first:  gh run download 38147956271 -n minervini-sweep-1d -D art/
Usage: python3 scripts/minervini_sweep_compare.py art/minervini_sweep_results_full_1d.json [--json out.json]

Faster-turnover tie-break (CLAUDE.md 2026-09-30): among cells that clear the floor, the one with the higher
PFnet per held bar is preferred ONLY if it is also confirmed on a main.py replay; this script never promotes.
"""
from __future__ import annotations

import argparse
import json
import sys

LIVE_TAG_HINT = "atr1d5"


def _rows(doc):
    res = doc.get("results", doc)
    if isinstance(res, dict):
        return list(res.items())
    return [(r.get("tag") or r.get("name"), r) for r in res]


def _f(r, *keys):
    for k in keys:
        if k in r and r[k] is not None:
            return r[k]
    return None


def analyse(doc, floor=1.1):
    out = []
    for tag, r in _rows(doc):
        net, gross = _f(r, "pfnet_net", "pfnet"), _f(r, "pfnet_gross")
        held = _f(r, "avg_held_bars", "avg_hold")
        exits = r.get("exits") or {}
        tot = sum(exits.values()) or 0
        share = {k: round(100.0 * v / tot, 1) for k, v in exits.items()} if tot else {}
        edge_per_bar = round((net - 1.0) / held, 4) if net and held else None
        out.append({"tag": tag, "n": _f(r, "n"), "pfnet": net, "pfgross": gross, "win_pct": _f(r, "win_pct"),
                    "avg_held_bars": held, "universe_size": _f(r, "universe_size"),
                    "exit_share_pct": share, "excess_pf_per_held_bar": edge_per_bar,
                    "clears_floor": bool(net is not None and net >= floor)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json")
    ap.add_argument("--floor", type=float, default=1.1)
    a = ap.parse_args(argv)
    rows = analyse(json.load(open(a.path)), a.floor)
    for r in rows:
        print(f"{r['tag']} | n {r['n']} | net {r['pfnet']} | gross {r['pfgross']} | win {r['win_pct']} | "
              f"hold {r['avg_held_bars']} | universe {r['universe_size']} | (PF-1)/bar {r['excess_pf_per_held_bar']} | "
              f"floor {r['clears_floor']} | exits {r['exit_share_pct']}")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
