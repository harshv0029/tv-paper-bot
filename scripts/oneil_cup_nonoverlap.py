#!/usr/bin/env python3
"""O'Neil cup-with-handle top cells (B-818) + B-831 mirror under strict FIFO non-overlap and an IS/OOS split.

Research only. Why: the run-38193479637 cells (scripts/oneil_research.py + oneil_patterns.py) were never checked
independently for one-position-per-symbol, nor split in-sample / out-of-sample. This harness reuses the UNCHANGED
detectors (oneil_patterns.pattern_signals, the same call oneil_research.entry_signals makes) and the UNCHANGED exit
engine (oneil_research.simulate), but for every signal bar simulates the trade it would open on its own, then keeps
a trade only if its signal bar is after the exit bar of the last kept trade (one position per symbol per cell; the
FIFO, split and tag helpers are macddiv_nonoverlap's, the aggregation helpers are oneil_nonoverlap's). Raw vs kept
counts are printed, not assumed equal (orx.simulate already skips signals before its previous exit, so kept n should
reproduce the original n on the same data; a difference is reported).

Sets (--sets):
  cup   1d oneil_cup_handle breakout, h60, chase 5/10, rs80 / rsqual1, atr3 AND avg1 (avg1 = averaging-down NEGATIVE
        CONTROL, which inflates PFnet; rank on the atr3 no-averaging cells), BOTH directions (short = reciprocal mirror,
        cells exist in the run-38193479637 TSV). 16 cells.
  b831  oneil_nonoverlap.py cells pivot_tight, leaders, exit_six with --mirror (long reproduction of run 38242267159
        plus the owed short mirror), same data, same shard composition.
Tags (new, never overwrite): <old minus __v1>__nonovl__v2, <old minus __v1>_nonovl_segis__v2 / _segoos__v2.
FULL universe via main._load_nse_universe_from_file() (sorted, interleaved shards; RS rank is the percentile within
the shard's ~1/N sample, exactly as in run 38193479637). 0.8% round trip (main.ROUND_TRIP_COST_PCT). Stop on every
trade. Candle size: cup/handle and RS rules are defined on daily bars (CFG bar counts); 1m-4h not applicable, stated.
Usage:
  python3 scripts/oneil_cup_nonoverlap.py run --shard 0 --nshards 3 --sets cup,b831 --out out/
  python3 scripts/oneil_cup_nonoverlap.py merge out/ --json res.json --tsv res.tsv [--ref docs/backtest_data/oneil_1d_run_38193479637.tsv]
"""
from __future__ import annotations

import argparse
import csv
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
import cell_tsv  # noqa: E402
import macddiv_nonoverlap as no  # noqa: E402  (fifo_filter, split_ts, segment_trades, nonovl_tag, seg_tag)
import oneil_nonoverlap as onl  # noqa: E402  (new_agg/add_trades/merge_agg/summarize, B-831 cells)
import oneil_patterns as op  # noqa: E402
import oneil_research as orx  # noqa: E402

TF = "1d"
CUP_FAMILY = "oneil_cup_handle"
CUP_HOLD = 60
CUP_CHASES = (0.05, 0.10)
CUP_RSF = ("80", "qual1")
CUP_EXITS = (("atr", 3.0), ("avg", 3.0))  # avg = avg1 negative control
DIRECTIONS = ("long", "short")


def cup_cells():
    """[(direction, chase, rsf, mode, val)] for the B-818 cells."""
    return [(d, ch, rsf, m, v) for d in DIRECTIONS for ch in CUP_CHASES for rsf in CUP_RSF for m, v in CUP_EXITS]


def old_tag(d, ch, rsf, mode, val, hold=CUP_HOLD, tf=TF):
    return orx.tag_for(CUP_FAMILY, "breakout", d, tf, ch, rsf, mode, val, hold)


def independent_trades(sig, o, h, l, c, atr, hold, mode, val, side, cost, swing_w):
    """One independent trade per signal bar (orx.simulate restricted to that single signal)."""
    out = []
    for t in np.flatnonzero(sig):
        one = np.zeros(len(sig), bool)
        one[t] = True
        rows = orx.simulate(one, o, h, l, c, atr, hold, mode, val, side, cost, swing_w)
        if rows:
            net, gross, held, reason = rows[0]
            e = int(t) + 1
            out.append({"entry_i": e, "exit_i": e + held - 1, "net": net, "gross": gross, "hold": held,
                        "reason": reason})
    return out


def nonovl_trades(sig, o, h, l, c, atr, hold, mode, val, side, cost, swing_w):
    """(kept, n_raw). orx.simulate's convention: the next SIGNAL bar must be after the previous exit bar, so the
    FIFO runs on signal bar = entry_i - 1 (entry is at least two bars after the last exit)."""
    raw = independent_trades(sig, o, h, l, c, atr, hold, mode, val, side, cost, swing_w)
    shifted = [{**t, "entry_i": t["entry_i"] - 1} for t in raw]
    kept = [{**t, "entry_i": t["entry_i"] + 1} for t in no.fifo_filter(shifted)]
    return kept, len(raw)


def run_symbol_cup(df, rs_series, cfg, cost, aggs, raw_counts, split_date="", split_frac=0.6, cells=None):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = rs_series.reindex(df.index).to_numpy(float)
    atr = orx.atr_arr(h, l, c)
    sigs = op.pattern_signals(o, h, l, c, v, rs, cfg, CUP_CHASES, orx.RS_FILTERS)
    ts = no.split_ts(df.index, split_date, split_frac)
    sym = getattr(df, "name", "") or ""
    for d, ch, rsf, mode, val in (cells or cup_cells()):
        sg = sigs.get((CUP_FAMILY, "breakout", d, ch, rsf))
        if sg is None or not sg.any():
            continue
        side = 1 if d == "long" else -1
        kept, nraw = nonovl_trades(sg, o, h, l, c, atr, CUP_HOLD, mode, val, side, cost, cfg["swing"])
        tag = old_tag(d, ch, rsf, mode, val)
        full = no.nonovl_tag(tag)
        onl.add_trades(aggs.setdefault(full, onl.new_agg()), kept, sym, df.index)
        ins, oos = no.segment_trades(kept, df.index, ts)
        onl.add_trades(aggs.setdefault(no.seg_tag(tag, "is"), onl.new_agg()), ins, sym, df.index)
        onl.add_trades(aggs.setdefault(no.seg_tag(tag, "oos"), onl.new_agg()), oos, sym, df.index)
        raw_counts[full] = raw_counts.get(full, 0) + nraw


def _fetch(syms, period, interval, min_bars):
    import yfinance as yf
    data = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=period, interval=interval, group_by="ticker", auto_adjust=True,
                            progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = orx.clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= min_bars:
                df.name = s
                data[s] = df
        print("downloaded", b0, "kept", len(data), flush=True)
    return data


def _shard(args):
    import main as app
    import universe_pin as up
    cfg = orx.CFG[TF]
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = up.select_universe(app._load_nse_universe_from_file(), args.pin_file or None)[args.shard::args.nshards]
    if args.maxsym:
        syms = syms[:args.maxsym]
    data = _fetch(syms, cfg["period"], "1d", cfg["min_bars"])
    closes = pd.DataFrame({s: df["Close"] for s, df in data.items()})
    rs_all = orx.rs_rank_matrix(closes, cfg["rs_lb"])
    sets = [x for x in args.sets.split(",") if x]
    idx_series = None
    if "b831" in sets:
        import yfinance as yf
        try:
            di = yf.download("^NSEI", period=cfg["period"], interval="1d", auto_adjust=True, progress=False)
            col = di["Close"]
            idx_series = (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna()
        except Exception as e:
            print("index download failed:", e, flush=True)
    aggs, raw_counts = {}, {}
    for i, (s, df) in enumerate(data.items()):
        try:
            if "cup" in sets:
                run_symbol_cup(df, rs_all[s], cfg, cost, aggs, raw_counts, args.split_date, args.split_frac)
            if "b831" in sets:
                onl.run_symbol(df, idx_series, rs_all[s], cfg, onl.ox.EX[TF], cost, TF,
                               ["pivot_tight", "leaders", "exit_six"], aggs, raw_counts, args.split_date,
                               args.split_frac, mirror=True)
        except Exception as e:
            print("ERROR", s, e, file=sys.stderr)
        if i % 100 == 0:
            print("processed", i, "tags", len(aggs), flush=True)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"oneil_cup_nonovl_{TF}_{args.shard}.json")
    with open(path, "w") as f:
        json.dump({"tf": TF, "sets": sets, "fetched": len(data), "universe": len(syms),
                   "fetched_symbols": sorted(data), "split_date": args.split_date, "split_frac": args.split_frac,
                   "raw_signal_trades": raw_counts, "aggs": aggs}, f, default=onl._jsonable)
    print(f"shard {args.shard}: fetched {len(data)}/{len(syms)} tags {len(aggs)} -> {path}")


def to_tsv_res(summary):
    """oneil_nonoverlap.summarize() output -> the finalize() shape cell_tsv expects (same TSV columns as run
    38193479637)."""
    if not summary.get("n"):
        return None
    top = summary.get("top5_trades") or []
    return {"n": summary["n"], "win_pct": summary["win_pct"], "pfnet": summary["pfnet"], "pfgross": summary["pfgross"],
            "avg_held_bars": summary["avg_hold_bars"], "avg_net_pct": summary["avg_net_pct"],
            "max_trade_net_pct": round(100.0 * top[0][0], 1) if top else None,
            "exit_reasons": summary["exit_reasons"]}


def ref_lookup(ref_tsv):
    if not ref_tsv or not os.path.exists(ref_tsv):
        return {}
    with open(ref_tsv) as fh:
        return {r["tag"]: r for r in csv.DictReader(fh, delimiter="\t")}


def original_tag(new_tag):
    """Map a __nonovl__v2 / _nonovl_seg*__v2 tag back to the run-38193479637 __v1 tag."""
    for suf in ("__nonovl__v2", "_nonovl_segis__v2", "_nonovl_segoos__v2"):
        if new_tag.endswith(suf):
            return new_tag[: -len(suf)] + "__v1"
    return None


def merge_dir(path, ref_tsv=None):
    merged, raw, fetched, fsyms = {}, {}, 0, set()
    for f in sorted(glob.glob(os.path.join(path, "**", "oneil_cup_nonovl_*.json"), recursive=True)):
        with open(f) as fh:
            d = json.load(fh)
        fetched += d["fetched"]
        fsyms.update(d.get("fetched_symbols", []))
        for t, n in d["raw_signal_trades"].items():
            raw[t] = raw.get(t, 0) + n
        for t, a in d["aggs"].items():
            onl.merge_agg(merged.setdefault(t, onl.new_agg()), a)
    ref = ref_lookup(ref_tsv)
    res = {}
    for t, a in merged.items():
        s = {**onl.summarize(a), "raw_signal_trades_before_fifo": raw.get(t)}
        o = ref.get(original_tag(t) or "")
        if o and t.endswith("__nonovl__v2"):
            s["orig_n"], s["orig_pfnet"] = int(o["n"]), float(o["pfnet"]) if o["pfnet"] else None
        res[t] = s
    return {"method": "strict FIFO, one position per symbol per cell; IS/OOS by entry bar", "fetched": fetched,
            "fetched_symbols": sorted(fsyms), "results": res}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=3)
    r.add_argument("--sets", default="cup,b831")
    r.add_argument("--maxsym", type=int, default=0)
    r.add_argument("--pin_file", default="")
    r.add_argument("--split_date", default="")
    r.add_argument("--split_frac", type=float, default=0.6)
    r.add_argument("--out", default="out")
    m = sub.add_parser("merge")
    m.add_argument("path")
    m.add_argument("--json")
    m.add_argument("--tsv")
    m.add_argument("--ref", default=os.path.join(ROOT, "docs", "backtest_data", "oneil_1d_run_38193479637.tsv"))
    args = ap.parse_args(argv)
    if args.cmd == "run":
        _shard(args)
        return 0
    out = merge_dir(args.path, args.ref)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, separators=(",", ":"), default=onl._jsonable)
    if args.tsv:
        tsv_res = {t: x for t, x in ((t, to_tsv_res(s)) for t, s in out["results"].items()) if x}
        cell_tsv.emit_full(tsv_res, args.tsv, "oneil_cup_nonoverlap")
    print("fetched", out["fetched"])
    for t, s in sorted(out["results"].items()):
        print(t, {k: s.get(k) for k in ("pfnet", "pfgross", "win_pct", "n", "avg_hold_bars", "pfnet_ex_top5",
                                        "raw_signal_trades_before_fifo", "orig_n", "orig_pfnet")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
