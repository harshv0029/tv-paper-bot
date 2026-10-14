"""Writes docs/mcx_live_cells.json: every exact-rule (no ATR stop) 1d MCX sweep cell with PFnet > 1, whose ATR-stopped variants also clear 1.1, on a
symbol that has a verified Kotak MCX mini mapping (GC/SI/CL/NG). main._MCX_DAILY_CELLS trades this list."""
import json, os
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
SYM = {"gc": "GC=F", "si": "SI=F", "cl": "CL=F", "ng": "NG=F"}
PARAMS = {"sma_crossover": {"fast": 9, "slow": 21}, "rsi_reversal": {"rsi_period": 14, "oversold": 30, "overbought": 70}}
r = json.load(open(os.path.join(D, "mcx_sweep_results.json")))
r = r.get("results", r)
# B-1270: a cell whose main-calling replay (docs/backtest_data/mcx_live_replay_run_*.json) is below PFnet 1.0 is not wired (one condition: replay PFnet >= 1).
import glob
REPLAY = {}
for fn in sorted(glob.glob(os.path.join(D, "backtest_data", "mcx_live_replay_run_*.json"))):
    for rr in json.load(open(fn)).get("rows", []):
        REPLAY[rr["tag"]] = rr["pfnet"]
cells = []
for tag, m in r.items():
    p = tag.split("__")
    if not isinstance(m, dict) or p[3] != "1d" or p[4] != "atrnone" or p[1] not in SYM or not (m.get("pfnet") or 0) > 1:
        continue
    if tag in REPLAY and REPLAY[tag] < 1.0:
        continue
    # 2026-10-11 user: no trade without a stop. Wire only if BOTH stopped variants (ATR 1.5 and 2.5) also clear 1.1.
    st = [r.get("__".join(p[:4] + [a, p[5]]), {}).get("pfnet") for a in ("atr1d5", "atr2d5")]
    if not all(x and x >= 1.1 for x in st):
        continue
    cells.append([tag, SYM[p[1]], p[0], PARAMS.get(p[0], {}), min(st)])
cells.sort(key=lambda c: -c[4])
json.dump({"cells": cells}, open(os.path.join(D, "mcx_live_cells.json"), "w"), indent=0)
print(len(cells))
