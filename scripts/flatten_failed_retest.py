#!/usr/bin/env python3
"""B-1120: planner for re-testing the flatten cells that FAILED the floor (research-only, read-only, no network).

Why: B-792's forced-15:15 flatten re-run (`_fl1515__v2`, 0.8% flat cost) left most cells below PFNET_LIVE_FLOOR. Two of its
own owed items were never run for them: the real MIS cost model (statutory + brokerage ~0.12%, 0.3% with slippage stress;
the 0.8% is the swing/CNC-style conservative figure) and the 1h/5m/15m readings. A cell that fails at 0.8% but clears at a
realistic MIS cost is a candidate, not a wiring: it still needs the real-main.py replay, and a changed cost is a NEW tag
(`..._cst0d3_..._fl1515__v2`), never an overwrite. Failed cells stay registered with their 0.8% numbers untouched.

What this does (derived at read time from strategy_registry.REGISTRY, nothing baked in):
  failed_cells()   flatten tags (`_fl1515__v2`, no cst param) whose stored PFnet < floor
  plan()           the (workflow family, interval) groups holding failed cells, the costs to run, retest tag names,
                   which retest tags are already registered (skipped), and what is owed (4h needs a 1h resample)
  --matrix         JSON for the workflow's fromJSON matrix
Runs through scripts/intraday_flatten_rerun.py (COST_PCT env), workflow .github/workflows/flatten-failed-retest.yml.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import intraday_flatten_rerun as fr  # noqa: E402

COSTS = (0.12, 0.3)          # MIS statutory+brokerage; incl. slippage stress (matches the chan_kalman_main 0.3% precedent)
RETEST_INTERVALS = ("5m", "15m", "1h")
OWED = ("4h needs a 1h->4h NSE-session resample in the flatten harness (not built; flagged, not skipped)",)


def _split_uni(name):
    """Pattern-family registry names carry a `|full` / `|n200` universe suffix after __v2; chan_kalman names do not."""
    base, _, uni = name.partition("|")
    return base, uni


def is_flatten_tag(name):
    base, _ = _split_uni(name)
    return base.endswith(fr.FLAT_TAG_SUFFIX + "__v2") and "_cst" not in base


def workflow_family(tag):
    """Workflow family that reproduces this tag's family; month/lunar follow their own `|full` / `|n200` universe suffix."""
    base, uni = _split_uni(tag)
    fam = base.split("__")[0]
    if fam.startswith("chan_kalman"):
        return "chan_kalman"
    if fam.startswith(("month", "lunar")):
        return "pattern_n200" if uni == "n200" else "pattern_full"
    return None


def failed_cells(registry=None, floor=None):
    import strategy_registry as sr
    reg = sr.REGISTRY if registry is None else registry
    fl = sr.PFNET_LIVE_FLOOR if floor is None else floor
    return [d for d in reg if is_flatten_tag(d.name) and d.metrics is not None and d.metrics.pfnet is not None and d.metrics.pfnet < fl]


def retest_tag(tag, cost_pct):
    """Retest tag for a 0.8% flatten tag at another cost: the cst param is inserted alphabetically; never collides."""
    if not is_flatten_tag(tag):
        raise ValueError(f"not a 0.8% flatten tag: {tag}")
    base, uni = _split_uni(tag)
    out = fr.flat_tag(fr.source_tag(base), cost_pct)
    return out + "|" + uni if uni else out


def plan(registry=None, floor=None, costs=COSTS, intervals=RETEST_INTERVALS):
    import strategy_registry as sr
    reg = sr.REGISTRY if registry is None else registry
    have = {d.name for d in reg}
    groups, unmapped, tags = {}, [], 0
    for d in failed_cells(reg, floor):
        tf = _split_uni(d.name)[0].split("__")[3]
        fam = workflow_family(d.name)
        if fam is None or tf not in intervals:
            unmapped.append(d.name)
            continue
        g = groups.setdefault((fam, tf), {"family": fam, "interval": tf, "failed": 0, "retests_new": 0, "retests_done": 0})
        g["failed"] += 1
        for c in costs:
            tags += 1
            g["retests_done" if retest_tag(d.name, c) in have else "retests_new"] += 1
    return {"costs": list(costs), "groups": [groups[k] for k in sorted(groups)], "failed_total": len(failed_cells(reg, floor)),
            "unmapped": sorted(unmapped), "retest_tags": tags, "owed": list(OWED)}


def matrix(registry=None, floor=None):
    """Matrix only for groups that still have a retest tag to produce."""
    p = plan(registry, floor)
    inc = [{"family": g["family"], "interval": g["interval"], "cost": c}
           for g in p["groups"] if g["retests_new"] for c in p["costs"]]
    return {"include": inc}


if __name__ == "__main__":
    if "--matrix" in sys.argv:
        print(json.dumps(matrix(), separators=(",", ":")))
    else:
        print(json.dumps(plan(), indent=1))
