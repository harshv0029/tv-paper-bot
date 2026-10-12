#!/usr/bin/env python3
"""O'Neil extension cells re-run under strict FIFO non-overlap + IS/OOS split (backlog B-831 / B-833). Research only.

Why: every O'Neil extension cell >= 1.1 (oneil-ext-research.yml run 38207070547 / 38147513010) was measured by
oneil_ext_research.simulate_x, with no IS/OOS split and no independent check of the one-position-per-symbol rule.
This harness reuses the UNCHANGED detectors (oneil_ext_research.bull_signals, mirror) and the UNCHANGED exit engine
(simulate_x), but for every signal bar simulates the trade it would open on its own, then applies a strict FIFO
filter (keep a trade only if its entry bar is after the exit bar of the last kept trade, one position per symbol
per cell; helpers shared with macddiv_nonoverlap). Raw vs kept counts are printed, not assumed equal.
Cells (--cells, default per --tf):
  pivot_tight  1d long  pivot breakout atr3 h40 x oneil_tightness pr1 / pr1d5 / pr2          (B-831 start)
  leaders      1d long  oneil_leaders__firsthigh atr2/atr3 h40
  exit_six     1d long  pivot exit xmsix125 (atr3, h130)
  shake1w      1w short oneil_shakeout__plus3 pm2, atr2/atr3 h8                              (B-833)
  --mirror adds the opposite direction of every cell as its own tag (both-directions rule).
Output per tag: PFnet net/gross, win %, avg hold (bars), n, raw signal trades before FIFO, exit reasons, top-5 trades,
PFnet with the global top-5 winners removed (bad-bar guard), count of >100% trades; plus IS and OOS (entry-bar split)
as separate tags <old minus __v1>__nonovl__v2 / _nonovl_segis__v2 / _segoos__v2. FULL universe via
main._load_nse_universe_from_file(); 0.8% round trip (main.ROUND_TRIP_COST_PCT); an ATR stop on every trade.
Usage:
  python3 scripts/oneil_nonoverlap.py run --tf 1d --shard 0 --nshards 3 --out out/
  python3 scripts/oneil_nonoverlap.py merge out/ --json oneil_nonoverlap.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import macddiv_nonoverlap as no  # noqa: E402  (strict-FIFO + IS/OOS helpers, tag helpers)
import oneil_ext_research as ox  # noqa: E402
import oneil_research as orx  # noqa: E402

TOPK = 20  # winners kept per tag per shard so the merge can drop the global top-5

# cell spec: (kind, direction, ...) ; kind in filter | entry | exit
CELL_SETS = {
    "pivot_tight": [("filter", "long", ("oneil_tightness", "range", k)) for k in ("r1", "r1d5", "r2")],
    "leaders": [("entry", "long", ("oneil_leaders", "firsthigh", "na"), 40, s) for s in (2.0, 3.0)],
    "exit_six": [("exit", "long", "six", 125)],
    "shake1w": [("entry", "short", ("oneil_shakeout", "plus3", "m2"), 8, s) for s in (2.0, 3.0)],
}
DEFAULT_CELLS = {"1d": "pivot_tight,leaders,exit_six", "1w": "shake1w"}


def independent_trades(sig, o, h, l, c, v, atr, hold, stopm, mode, val, exarr, side, cost, ex):
    """One independent trade per signal bar (simulate_x restricted to that single signal)."""
    out = []
    for t in np.flatnonzero(sig):
        one = np.zeros(len(sig), bool)
        one[t] = True
        rows = ox.simulate_x(one, o, h, l, c, v, atr, hold, stopm, mode, val, exarr, side, cost, ex)
        if rows:
            net, gross, held, reason = rows[0]
            e = int(t) + 1
            out.append({"entry_i": e, "exit_i": e + held - 1, "net": net, "gross": gross, "hold": held, "reason": reason})
    return out


def nonovl_trades(*a, **k):
    """Strict FIFO with simulate_x's own convention: the NEXT SIGNAL bar must be after the previous exit bar
    (so the re-entry open is at least two bars after it), i.e. fifo on signal bar = entry_i - 1."""
    raw = independent_trades(*a, **k)
    shifted = [{**t, "entry_i": t["entry_i"] - 1} for t in raw]
    kept = [{**t, "entry_i": t["entry_i"] + 1} for t in no.fifo_filter(shifted)]
    return kept, len(raw)


def new_agg():
    return {"n": 0, "wins": 0, "gain": 0.0, "loss": 0.0, "gain_g": 0.0, "loss_g": 0.0, "held": 0, "gt100": 0,
            "reasons": {}, "top": []}


def add_trades(agg, trades, sym="", idx=None):
    for t in trades:
        net, gross = t["net"], t["gross"]
        agg["gain" if net > 0 else "loss"] += abs(net)
        agg["gain_g" if gross > 0 else "loss_g"] += abs(gross)
        agg["n"] += 1
        agg["wins"] += int(net > 0)
        agg["held"] += t["hold"]
        agg["gt100"] += int(net > 1.0)
        r = agg["reasons"].setdefault(t["reason"], [0, 0.0])
        r[0] += 1
        r[1] += net
        d = str(idx[min(t["entry_i"], len(idx) - 1)])[:10] if idx is not None else ""
        agg["top"].append([round(net, 4), sym, d, t["reason"], t["hold"]])
    agg["top"] = sorted(agg["top"], key=lambda x: -x[0])[:TOPK]


def merge_agg(dst, src):
    for k in ("n", "wins", "gain", "loss", "gain_g", "loss_g", "held", "gt100"):
        dst[k] += src[k]
    for rk, (rn, rs) in src["reasons"].items():
        r = dst["reasons"].setdefault(rk, [0, 0.0])
        r[0] += rn
        r[1] += rs
    dst["top"] = sorted(dst["top"] + src["top"], key=lambda x: -x[0])[:TOPK]


def summarize(a):
    if not a["n"]:
        return {"n": 0}
    top5 = [t[0] for t in a["top"][:5]]
    g_ex = a["gain"] - sum(x for x in top5 if x > 0)
    return {
        "n": a["n"],
        "pfnet": round(a["gain"] / a["loss"], 3) if a["loss"] > 0 else None,
        "pfgross": round(a["gain_g"] / a["loss_g"], 3) if a["loss_g"] > 0 else None,
        "win_pct": round(100.0 * a["wins"] / a["n"], 1),
        "avg_hold_bars": round(a["held"] / a["n"], 2),
        "avg_net_pct": round(100.0 * (a["gain"] - a["loss"]) / a["n"], 3),
        "pfnet_ex_top5": round(g_ex / a["loss"], 3) if a["loss"] > 0 else None,
        "n_trades_gt100pct": a["gt100"],
        "top5_trades": a["top"][:5],
        "exit_reasons": {k: {"n": r[0], "avg_net_pct": round(100.0 * r[1] / r[0], 3)} for k, r in a["reasons"].items()},
    }


def cell_tag(spec, tf, d, ex_cfg, holds):
    """(registry-style old tag, hold) for a cell spec in direction d."""
    kind = spec[0]
    if kind == "filter":
        base_h = holds[1]
        bt = ox.ptag("oneil_pivot", "breakout", d, tf, {"h": base_h, "atr": 3.0, "chase": 10})
        ffam, fvar, fpk = spec[2]
        return ox.combo(bt, ox.ptag(ffam, fvar, d, tf, {"p": fpk})), base_h
    if kind == "entry":
        fam, var, pk = spec[2]
        p = {"h": spec[3], "atr": spec[4]}
        if pk != "na":
            p["p"] = pk
        return ox.ptag(fam, var, d, tf, p), spec[3]
    mode, val = spec[2], spec[3]
    hold = ex_cfg["six"] + 5
    return ox.ptag("oneil_pivot", "exit", d, tf, {"h": hold, "atr": 3.0, "chase": 10, "xm": mode + str(int(val))}), hold


def run_symbol(df, idx_series, rs_series, cfg, ex, cost, tf, cells_sel, aggs, raw_counts, split_date="", split_frac=0.6,
               mirror=False):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = rs_series.reindex(df.index).to_numpy(float)
    idx = None
    if idx_series is not None:
        idx = idx_series.reindex(df.index).ffill().to_numpy(float)
        if np.isnan(idx).all():
            idx = None
    atr = orx.atr_arr(h, l, c)
    ts = no.split_ts(df.index, split_date, split_frac)
    sym = getattr(df, "name", "") or ""
    for d_native, side in (("long", 1), ("short", -1)):
        sigs = None
        for name in cells_sel:
            for spec in CELL_SETS[name]:
                if d_native != spec[1] and not mirror:
                    continue
                if sigs is None:
                    arrs = (o, h, l, c, idx, rs) if d_native == "long" else ox.mirror(o, h, l, c, idx, rs)
                    sigs = ox.bull_signals(arrs[0], arrs[1], arrs[2], arrs[3], v, arrs[4], arrs[5], cfg, ex)
                E, brk, F, X = sigs
                kind = spec[0]
                mode, val, stopm = "base", 0, 3.0
                if kind == "filter":
                    fm = F.get(spec[2])
                    if fm is None:
                        continue
                    sg = brk & fm
                elif kind == "entry":
                    sg = E.get(spec[2])
                    if sg is None:
                        continue
                    stopm = spec[4]
                else:
                    mode, val = spec[2], ex["six"]
                    sg = brk
                tag, hold = cell_tag(spec, tf, d_native, ex, cfg["holds"])
                if not np.asarray(sg).any():
                    continue
                kept, nraw = nonovl_trades(sg, o, h, l, c, v, atr, hold, stopm, mode, val, None, side, cost, ex)
                full = no.nonovl_tag(tag)
                add_trades(aggs.setdefault(full, new_agg()), kept, sym, df.index)
                ins, oos = no.segment_trades(kept, df.index, ts)
                add_trades(aggs.setdefault(no.seg_tag(tag, "is"), new_agg()), ins, sym, df.index)
                add_trades(aggs.setdefault(no.seg_tag(tag, "oos"), new_agg()), oos, sym, df.index)
                raw_counts[full] = raw_counts.get(full, 0) + nraw


def _shard(args):
    import yfinance as yf
    import main as app
    tf = args.tf
    cfg, ex = orx.CFG[tf], ox.EX[tf]
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = sorted(set(app._load_nse_universe_from_file()))[args.shard::args.nshards]
    if args.maxsym:
        syms = syms[:args.maxsym]
    period = args.period or cfg["period"]
    interval = "1wk" if tf == "1w" else "1d"
    idx_series = None
    try:
        di = yf.download("^NSEI", period=period, interval=interval, auto_adjust=True, progress=False)
        col = di["Close"]
        idx_series = (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna()
    except Exception as e:
        print("index download failed:", e, flush=True)
    data = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=period, interval=interval, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = orx.clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= cfg["min_bars"]:
                df.name = s
                data[s] = df
    closes = pd.DataFrame({s: df["Close"] for s, df in data.items()})
    rs_all = orx.rs_rank_matrix(closes, cfg["rs_lb"])
    cells_sel = [x for x in (args.cells or DEFAULT_CELLS[tf]).split(",") if x]
    aggs, raw_counts = {}, {}
    for i, (s, df) in enumerate(data.items()):
        try:
            run_symbol(df, idx_series, rs_all[s], cfg, ex, cost, tf, cells_sel, aggs, raw_counts, args.split_date,
                       args.split_frac, args.mirror)
        except Exception as e:
            print("ERROR", s, e, file=sys.stderr)
        if i % 100 == 0:
            print("processed", i, "tags", len(aggs), flush=True)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"oneil_nonovl_{tf}_{args.shard}.json"), "w") as f:
        json.dump({"tf": tf, "cells": cells_sel, "fetched": len(data), "universe": len(syms), "split_date": args.split_date,
                   "split_frac": args.split_frac, "raw_signal_trades": raw_counts, "aggs": aggs}, f)
    print(f"shard {args.shard} {tf}: fetched {len(data)}/{len(syms)} tags {len(aggs)}")


def merge_dir(path):
    merged, raw, fetched = {}, {}, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "oneil_nonovl_*.json"), recursive=True)):
        with open(f) as fh:
            d = json.load(fh)
        fetched += d["fetched"]
        for t, n in d["raw_signal_trades"].items():
            raw[t] = raw.get(t, 0) + n
        for t, a in d["aggs"].items():
            merge_agg(merged.setdefault(t, new_agg()), a)
    res = {t: {**summarize(a), "raw_signal_trades_before_fifo": raw.get(t)} for t, a in merged.items()}
    return {"method": "strict FIFO, one position per symbol per cell; IS/OOS by entry bar", "fetched": fetched, "results": res}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tf", default=os.environ.get("TF", "1d"), choices=("1d", "1w"))
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=3)
    r.add_argument("--cells", default="", help="comma list of " + ",".join(CELL_SETS))
    r.add_argument("--mirror", action="store_true", help="also run the opposite direction (separate tags)")
    r.add_argument("--period", default="")
    r.add_argument("--maxsym", type=int, default=0)
    r.add_argument("--split_date", default="")
    r.add_argument("--split_frac", type=float, default=0.6)
    r.add_argument("--out", default="out")
    m = sub.add_parser("merge")
    m.add_argument("path")
    m.add_argument("--json")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        _shard(args)
        return 0
    out = merge_dir(args.path)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, separators=(",", ":"))
    for t, s in sorted(out["results"].items()):
        print(t, {k: s.get(k) for k in ("pfnet", "pfgross", "win_pct", "n", "avg_hold_bars", "pfnet_ex_top5", "raw_signal_trades_before_fifo")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
