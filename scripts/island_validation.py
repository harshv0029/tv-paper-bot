#!/usr/bin/env python3
"""Island-reversal validation harness (backlog B-789). Research only, no live wiring.

Why: reversal__island__long__1d__atr3_within8__v1 printed PFnet 1.571 (n 8837, hold 7.7d) in the
Elder merge, but a gap-down followed by a gap-up inside 8 bars is also what stale prints and
illiquid micro-caps produce. This harness re-tests the SAME detector (logic of
scripts/elder_patterns_research.d_island, copied so filters can be added) with the owed checks:
  * gross vs net (pf_gross printed next to pfnet), per-trade win/loss sums kept
  * ex-top-5 PFnet (global top-5 winners removed at merge)
  * per-calendar-year PFnet (is the edge one year / one regime?)
  * liquidity and gap-size filters: none | px20 (close>=20) | turn1cr (20d median close*vol >= 1e7)
    | gap05 (both gaps >= 0.5 ATR) | liq_gap (px20+turn1cr+gap05)
  * both directions via the reciprocal-price mirror (short = separate tag), ATR sweep 1.5/2/3
  * one position per symbol per cell (er.simulate's free-slot rule), i.e. non-overlapping
  * candle size via --interval/--period (bar-count constants change meaning; 4h owed: needs 1h resample)
B-815 adds, for the long cells >= 1.1 (filters none/px20/turn1cr/gap05 x ATR 1.5/2/3): strict-FIFO tags
<old minus __v1>__nonovl__v2 plus IS/OOS split tags <old minus __v1>__segis__v2 / __segoos__v2 (split by entry date).
Tags: reversal__island_<filter>__<dir>__<tf>__atr<m>_within8__v1 (old unfiltered tag stays untouched).
Full universe: main._load_nse_universe_from_file().

Usage:
  python3 scripts/island_validation.py run --shard 0 --nshards 4 --interval 1d --period 5y --out out/
  python3 scripts/island_validation.py merge out/ --json island_validation.json
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
import macddiv_nonoverlap as no  # noqa: E402  (shared strict-FIFO + IS/OOS helpers)

FILTERS = ("none", "px20", "turn1cr", "gap05", "liq_gap")
WITHIN = 8
TOP_K = 5


def island_entries(df, within=WITHIN, min_gap_atr=0.0):
    """Long-orientation island bottom: gap down at i, gap up at j<=i+within above the gap-down bar's high."""
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    a = er.atr(df).to_numpy()
    n = len(df)
    ent = np.zeros(n, bool)
    for i in range(1, n):
        if not h[i] < l[i - 1]:
            continue
        if min_gap_atr and not (l[i - 1] - h[i] >= min_gap_atr * a[i - 1] > 0):
            continue
        for j in range(i + 1, min(n, i + within + 1)):
            if l[j] > h[j - 1] and l[j] > h[i]:
                if min_gap_atr and not (l[j] - h[i] >= min_gap_atr * a[j - 1] > 0):
                    break
                ent[j] = True
                break
    return ent


def _exit_ema(df):
    e = er.ema(df["Close"], 13)
    return ((df["Close"] < e) & (e < e.shift(1))).to_numpy()


def flip(df):
    m = pd.DataFrame(index=df.index)
    m["Open"], m["High"], m["Low"], m["Close"] = 1 / df["Open"], 1 / df["Low"], 1 / df["High"], 1 / df["Close"]
    m["Volume"] = df["Volume"]
    return m


def liquidity_mask(df):
    px = df["Close"].to_numpy(float)
    turn = (df["Close"] * df["Volume"]).rolling(20).median().to_numpy()
    return px >= 20, np.nan_to_num(turn) >= 1e7


def build_signal(df, flt):
    n = len(df)
    gap = 0.5 if flt in ("gap05", "liq_gap") else 0.0
    pxm, tm = liquidity_mask(df)
    mask = np.ones(n, bool)
    if flt in ("px20", "liq_gap"):
        mask &= pxm
    if flt in ("turn1cr", "liq_gap"):
        mask &= tm
    mir = flip(df)
    le = island_entries(df, min_gap_atr=gap) & mask
    se = island_entries(mir, min_gap_atr=gap) & mask
    return er._pack(df, le, se, _exit_ema(df), _exit_ema(mir))


def new_agg():
    a = er.new_agg()
    a["top"] = []
    a["year"] = {}
    return a


def add(agg, trades, idx, cost=er.COST_ROUND_TRIP):
    er.add_trades(agg, trades, cost)
    for t in trades:
        r = t["ret"]
        if r > 0:
            agg["top"] = sorted(agg["top"] + [r], reverse=True)[:TOP_K]
        y = str(idx[min(t["s"] + 1, len(idx) - 1)].year)
        w, l, n = agg["year"].get(y, [0.0, 0.0, 0])
        agg["year"][y] = [w + max(r, 0.0), l + max(-r, 0.0), n + 1]


def run_symbol(df, tf, aggs):
    for flt in FILTERS:
        sig = build_signal(df, flt)
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag("reversal", f"island_{flt}", direction, tf, {"atr": am, "within": WITHIN})
                add(aggs.setdefault(tag, new_agg()), er.simulate(df, sig, direction, am), df.index)


# B-815: long cells that were PFnet >= 1.1 in run 38192367677 (filters x ATR 1.5/2/3), re-run with strict FIFO
# (one position per symbol per cell, independent trades then filter) and an IS/OOS split on entry date.
NONOVL_FILTERS = ("none", "px20", "turn1cr", "gap05")


def nonovl_seg_tag(old, seg):
    base = old[:-4] if old.endswith("__v1") else old
    return f"{base}__seg{seg}__v2"


def run_symbol_nonovl(df, tf, aggs, split_date="", split_frac=0.6):
    ts = no.split_ts(df.index, split_date, split_frac)
    for flt in NONOVL_FILTERS:
        sig = build_signal(df, flt)
        if not sig["long"].any():
            continue
        for am in er.ATR_MULTS:
            base = er.make_tag("reversal", f"island_{flt}", "long", tf, {"atr": am, "within": WITHIN})
            kept, _ = no.cell_trades(df, sig, "long", am)
            ins, oos = no.segment_trades(kept, df.index, ts)
            for tag, trs in ((no.nonovl_tag(base), kept), (nonovl_seg_tag(base, "is"), ins),
                             (nonovl_seg_tag(base, "oos"), oos)):
                add(aggs.setdefault(tag, new_agg()), trs, df.index)


def summarize(agg):
    s = er.summarize(agg)
    top = agg["top"][:TOP_K]
    ws, ls = agg["win_sum"] - sum(top), agg["loss_sum"]
    s["pfnet_ex_top5"] = round(ws / ls, 3) if ls > 0 else None
    s["by_year"] = {y: {"pfnet": round(w / l, 3) if l > 0 else None, "n": n}
                    for y, (w, l, n) in sorted(agg["year"].items())}
    return s


def cmd_run(a):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % a.nshards == a.shard]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, a.period, a.interval)
            if raw is None or len(raw) < 120:
                continue
            df = er.prep(raw)
            fetched += 1
            run_symbol(df, a.interval, aggs)
            run_symbol_nonovl(df, a.interval, aggs, a.split_date, a.split_frac)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    json.dump({"interval": a.interval, "split_date": a.split_date, "split_frac": a.split_frac, "fetched": fetched, "universe": len(syms), "aggs": aggs},
              open(os.path.join(a.out, f"island_{a.interval}_{a.shard}.json"), "w"))
    print(f"island shard {a.shard}: fetched {fetched}/{len(syms)} cells {len(aggs)}")


def merge_dir(path):
    tot, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "island_*.json"))):
        d = json.load(open(f))
        fetched += d["fetched"]
        universe += d["universe"]
        for tag, ag in d["aggs"].items():
            t = tot.setdefault(tag, new_agg())
            er.merge_aggs(t, ag)
            t["top"] = sorted(t["top"] + ag["top"], reverse=True)[:TOP_K]
            for y, (w, l, n) in ag["year"].items():
                cur = t["year"].setdefault(y, [0.0, 0.0, 0])
                t["year"][y] = [cur[0] + w, cur[1] + l, cur[2] + n]
    out = {tag: summarize(ag) for tag, ag in sorted(tot.items())}
    return {"universe_listed": universe, "universe_with_data": fetched, "cells": out}


def cmd_merge(a):
    res = merge_dir(a.path)
    print(f"universe listed {res['universe_listed']} with data {res['universe_with_data']}")
    print("tag | n | pfnet | pf_gross | ex_top5 | win% | hold | exits")
    for tag, s in res["cells"].items():
        print(f"{tag} | {s['n']} | {s['pfnet']} | {s['pf_gross']} | {s['pfnet_ex_top5']} | {s['win_pct']} | "
              f"{s['avg_hold_bars']} | {s['exit_reasons']}")
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=4)
    r.add_argument("--interval", default="1d")
    r.add_argument("--period", default="5y")
    r.add_argument("--split_date", default="", help="IS/OOS boundary (entry date < it = IS); blank = split_frac")
    r.add_argument("--split_frac", type=float, default=0.6)
    r.add_argument("--out", default="out")
    mg = sub.add_parser("merge")
    mg.add_argument("path")
    mg.add_argument("--json")
    a = ap.parse_args(argv)
    return (cmd_run if a.cmd == "run" else cmd_merge)(a) or 0


if __name__ == "__main__":
    sys.exit(main())
