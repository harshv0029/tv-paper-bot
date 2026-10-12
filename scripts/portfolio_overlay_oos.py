#!/usr/bin/env python3
"""Out-of-sample (time-split) harness for portfolio-overlay candidates (backlog B-801). Research only.

Candidates from B-800 (run 38176399634), both on the brk20 base entry, both directions, every ATR multiple:
  pricebucket  entry price < 20 (hi20_lo0), candidate pfovl__brk20_pricebucket__long__1d__atr3_hi20_lo0__v1
  passtrade4   portfolio sim, 2% risk, K=10, skip when stop distance > 4% (passtrade4_k10)
  base         the unfiltered brk20 stream, for reference
Each candidate is evaluated on THREE windows of the same trade stream, split by ENTRY DATE (not by trade
count): full, in-sample (earliest `--is-pct` % of the distinct entry dates, default 60) and out-of-sample
(the remaining dates). The split date is derived from the data and printed. The overlay rule has no fitted
parameter besides the ones listed, so OOS = same rule applied untouched to later dates; passtrade4 is
re-simulated from scratch inside each window (fresh equity, empty book). Trades that enter in a window are
kept even if they exit after the cut (stated approximation).
Stage 1 reuses portfolio_overlay_research.py collect (same streams). Stage 2 = `merge` below.
Every row: PFnet net and gross, win %, n, avg hold bars, universe. Each (overlay, window, direction, ATR)
is its own tag (family pfoos); nothing is pooled. Viability stays derived at read time.

Usage: python3 scripts/portfolio_overlay_oos.py merge --dir shards/ --json pfoos_results.json [--is-pct 60]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import portfolio_overlay_research as po  # noqa: E402

TF = "1d"
BASE = "brk20"
PRICE_HI = 20
SKIP_RF = 0.04


def split_cut(trades, is_pct=60):
    """Entry-second cutoff: first is_pct % of distinct entry DAYS are in-sample."""
    days = sorted({t[0] // 86400 for t in trades})
    if len(days) < 2:
        return None
    k = max(1, min(len(days) - 1, int(len(days) * is_pct / 100)))
    return days[k] * 86400


def windows(trades, is_pct=60):
    cut = split_cut(trades, is_pct)
    if cut is None:
        return {"full": trades, "is": [], "oos": []}, None
    return {"full": trades, "is": [t for t in trades if t[0] < cut], "oos": [t for t in trades if t[0] >= cut]}, cut


def overlay_trades(name, trades):
    if name == "base":
        return trades
    if name == "pricebucket":
        return [t for t in trades if 0 <= t[5] < PRICE_HI]
    if name == "passtrade4":
        return po.simulate_portfolio(trades, K=10, risk=0.02, policy={"skip_rf": SKIP_RF})["taken"]
    raise ValueError(name)


OVERLAYS = {"base": {"x": 0}, "pricebucket": {"hi": PRICE_HI, "lo": 0}, "passtrade4": {"k": 10}}


def merge(path, json_out=None, is_pct=60):
    streams, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "collect_*.json"), recursive=True)):
        d = json.load(open(f))
        fetched += d["fetched"]
        universe += d["universe"]
        for k, v in d["streams"].items():
            streams.setdefault(k, []).extend(v)
    rows, cuts = [], {}
    for key, tr in sorted(streams.items()):
        base, direction, am = key.split("|")
        if base != BASE:
            continue
        tr.sort(key=lambda t: (t[0], t[1]))
        win, cut = windows(tr, is_pct)
        cuts[key] = cut
        for oname, params in OVERLAYS.items():
            for wname, wtr in win.items():
                st = po.stats(overlay_trades(oname, wtr)) if wtr else po.stats([])
                tag = er.make_tag("pfoos", f"{BASE}_{oname}_{wname}{is_pct if wname != 'full' else ''}", direction, TF,
                                  {**params, "atr": float(am)})
                rows.append({"tag": tag, "overlay": oname, "window": wname, "direction": direction, "atr": float(am),
                             "is_pct": is_pct, "split_ts": cut, **st, "universe": universe})
    res = {"universe_size": universe, "symbols_fetched": fetched, "cost_round_trip": po.COST, "is_pct": is_pct,
           "split_ts_by_stream": cuts, "rows": rows}
    print(f"universe {universe} fetched {fetched} is_pct {is_pct} rows {len(rows)}")
    for k, c in sorted(cuts.items()):
        if c:
            print(f"split {k}: IS entries < {np.datetime64(int(c), 's')}")
    print(f"{'tag':96s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}")
    for rw in rows:
        print(f"{rw['tag']:96s} {rw['n']:7d} {str(rw['pfnet']):>7s} {str(rw['pf_gross']):>8s} "
              f"{rw['win_pct']:6.1f} {rw['avg_hold_bars']:5.1f}")
    if json_out:
        json.dump(res, open(json_out, "w"), indent=1)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--dir", required=True)
    m.add_argument("--json")
    m.add_argument("--is-pct", type=int, default=60)
    a = ap.parse_args(argv)
    merge(a.dir, a.json, a.is_pct)
    return 0


if __name__ == "__main__":
    sys.exit(main())
