"""Prints the brk20 replay job matrix as JSON (env: INTERVALS, DIRECTIONS, ATRS, RRS, BES, NSHARDS).
Matrix = interval x direction x shard; every job replays ALL (atr, rr, be) cells for its slice of the
universe, and the aggregate job merges shards exactly (raw sums). BES: 'none' = baseline (no ratchet),
numbers = breakeven-at-R. Capped at 40 jobs per the one-running-plus-one-queued Actions rule."""
import itertools
import json
import os
import sys


def _csv(name, default):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def build(env=None):
    e = env if env is not None else os.environ
    get = lambda k, d: [x.strip() for x in e.get(k, d).split(",") if x.strip()]
    intervals, dirs = get("INTERVALS", "1d,1h,15m"), get("DIRECTIONS", "long,short")
    atrs, rrs, bes = get("ATRS", "3,4"), get("RRS", "3,3.5,4"), get("BES", "none,1")
    nshards = int(e.get("NSHARDS", "6"))
    for d in dirs:
        if d not in ("long", "short"):
            raise SystemExit(f"bad direction {d}")
    for i in intervals:
        if i not in ("1d", "4h", "1h", "15m", "5m"):
            raise SystemExit(f"bad interval {i}")
    cells = [{"atr": float(a), "rr": float(r), "be": None if b == "none" else float(b)}
             for a, r, b in itertools.product(atrs, rrs, bes)]
    inc = [{"interval": i, "direction": d, "shard": s, "nshards": nshards, "cells": json.dumps(cells)}
           for i in intervals for d in dirs for s in range(nshards)]
    if len(inc) > 40:
        raise SystemExit(f"matrix too large: {len(inc)} (reduce intervals/directions/nshards)")
    return {"include": inc}


if __name__ == "__main__":
    print(json.dumps(build()))
