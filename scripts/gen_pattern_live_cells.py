"""Generates docs/pattern_live_cells.json: every registry strategy that can be wired into the live daily swing
pattern engine (main._run_pattern_cell_entries). One row per distinct (rule, ETF-or-stock, hold, ATR stop).

Inclusion rules (all must hold): source is pattern_lab/combo_lab; LONG; 1d; has a real ATR stop (atr > 0, the live
engine never holds a position without a protective stop); registry status VALIDATED or LIVE (PFnet > 1 and n >= 300,
OOS-gated for combos and wired stock cells by the registry loader); not the pooled `_full` universe variant (live swing
universe is NIFTY-200 stocks plus ETFs). Ordered best PFnet first: the engine takes the first matching cell per symbol.
Run: python scripts/gen_pattern_live_cells.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "pattern_live_cells.json")


def rule_key(tag):
    p = tag.split("__")
    if p[0] == "combo":
        a, b = p[1].split("_x_")
        return f"{a}&{b}", False
    variant = p[1]
    etf = variant.endswith("_etf")
    for suf in ("_etf", "_full"):
        if variant.endswith(suf):
            variant = variant[: -len(suf)]
    return (p[0] if variant == "base" else f"{p[0]}_{variant}"), etf


def build():
    import strategy_registry as sr
    best = {}
    for s in sr.REGISTRY:
        src = s.source or ""
        if s.timeframe != "1d" or not ("pattern_lab" in src or "combo_lab" in src):
            continue
        if s.status.name not in ("VALIDATED", "LIVE") or not s.metrics or not s.metrics.pfnet or s.metrics.pfnet <= 1:
            continue
        p = s.name.split("__")
        if len(p) < 6 or p[2] != "long" or p[0] in ("baseline", "sector_rotation"):
            continue
        m = re.match(r"atr(none|\d+(?:d\d+)?)_h(\d+)", p[4])
        if not m or m.group(1) == "none" or p[1].endswith("_full"):
            continue
        k = float(m.group(1).replace("d", "."))
        rule, etf = rule_key(s.name)
        key = (rule, etf, int(m.group(2)), k)
        if key not in best or s.metrics.pfnet > best[key][0]:
            best[key] = (s.metrics.pfnet, s.name)
    rows = sorted(best.items(), key=lambda kv: -kv[1][0])
    return [[name, rule, hold, k, round(pf, 3)] for (rule, etf, hold, k), (pf, name) in rows]


if __name__ == "__main__":
    rows = build()
    json.dump({"cells": rows}, open(OUT, "w"), indent=0)
    print(len(rows), "cells")
