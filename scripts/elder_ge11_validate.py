#!/usr/bin/env python3
"""B-850 / B-852 validation harness for the Elder cells that cleared PFnet 1.1 in run 38208431466. Research only.

Cells: gaps exhaust_fade + common_fade (nb 3/4/5) and macd hist_exhaust (zf1), BOTH directions, ATR 1.5/2/3, via the
UNCHANGED variant functions of elder_macd_dirgap_research and the UNCHANGED er.simulate (stop on every trade, 0.8% cost,
bad-bar guard B-864, which run 38208431466 predates). Adds what that run lacked:
  * strict FIFO re-check (er.simulate already skips signals before its previous exit, so raw == kept is EXPECTED;
    counted, not assumed);
  * chronological IS/OOS split at IS_FRAC of each symbol's bars by signal bar (tags ..._segis / ..._segoos);
  * regime split by the symbol's own close vs its SMA200 at the signal bar (..._segbull / ..._segbear) to test whether
    the long fade is a rising-market artefact (B-852);
  * pfnet_trim1 and pfnet_trim5 (ex top-5 winners) per tag; v3 tags (new run = new tag; v1/v2 untouched);
  * candle sweep: --interval 1d|1h|15m|5m|4h (4h = 1h fetch resampled with scripts/resample_4h.py, NSE session anchored);
  * --pin-file for an identical symbol set across reruns (B-841).
Verdict (merge): a pooled cell is CONFIRMED only if pooled PFnet, OOS PFnet, pooled trim5 and OOS trim5 are all
>= strategy_registry.PFNET_LIVE_FLOOR AND OOS n >= MIN_OOS_N (30). Bear-regime PFnet is reported, informational.
Bar-count constants (nb, 30-bar max hold) change meaning with the interval; hold is reported in bars.
Usage: python3 scripts/elder_ge11_validate.py run --interval 1d --period 5y --shard 0 --nshards 8 --out out/
       python3 scripts/elder_ge11_validate.py merge out/ --json ge11_results.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import elder_indicators_research as er  # noqa: E402
import elder_macd_dirgap_research as g  # noqa: E402
import universe_pin as up  # noqa: E402

IS_FRAC = 0.6
MIN_OOS_N = 30
VERSION = 3
SEGS = ("is", "oos", "bull", "bear")
PERIODS = {"1d": "5y", "1h": "730d", "4h": "730d", "15m": "60d", "5m": "60d"}


def wanted():
    out = []
    for fam in ("gaps", "macd"):
        for v, p, fn, m in g.variant_specs(fam):
            if (fam == "gaps" and v in ("exhaust_fade", "common_fade")) or (fam == "macd" and v == "hist_exhaust"):
                out.append((fam, v, p, fn, m))
    return out


def fifo_filter(trades):
    kept, last_exit = [], -1
    for t in sorted(trades, key=lambda x: x["s"]):
        e = t["s"] + 1
        if e <= last_exit:
            continue
        kept.append(t)
        last_exit = e + t["hold"] - 1
    return kept


def seg_tag(tag, seg):
    return tag[:-len(f"__v{VERSION}")] + f"_seg{seg}__v{VERSION}"


def is_seg_tag(tag):
    return "_seg" in tag.split("__")[4]


def new_agg():
    a = er.new_agg()
    a["raw_n"] = 0
    return a


def run_symbol(df, tf, aggs):
    cut = int(len(df) * IS_FRAC)
    sma = df["Close"].rolling(200).mean().to_numpy()
    close = df["Close"].to_numpy(float)
    for fam, variant, params, fn, mgmt in wanted():
        try:
            sig = fn(df)
        except Exception as ex:  # noqa: BLE001
            print("VARIANT ERROR", fam, variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                raw = er.simulate(df, sig, direction, am, mgmt)
                trades = fifo_filter(raw)
                tag = er.make_tag(fam, variant, direction, tf, {**params, "atr": am}, version=VERSION)
                pooled = aggs.setdefault(tag, new_agg())
                pooled["raw_n"] += len(raw)
                er.add_trades(pooled, trades)
                sel = {
                    "is": [t for t in trades if t["s"] < cut],
                    "oos": [t for t in trades if t["s"] >= cut],
                    "bull": [t for t in trades if not np.isnan(sma[t["s"]]) and close[t["s"]] > sma[t["s"]]],
                    "bear": [t for t in trades if not np.isnan(sma[t["s"]]) and close[t["s"]] <= sma[t["s"]]],
                }
                for seg in SEGS:
                    er.add_trades(aggs.setdefault(seg_tag(tag, seg), new_agg()), sel[seg])


def _load(m, sym, period, interval):
    if interval == "4h":
        import resample_4h as r4
        raw = m.fetch_ohlc(sym, period, "1h")
        return None if raw is None else r4.resample_1h_to_4h(raw)
    return m.fetch_ohlc(sym, period, interval)


def shard(a):
    import main as m
    syms = up.select_universe(sorted(set(m._load_nse_universe_from_file())), a.pin_file or None)
    syms = [s for k, s in enumerate(syms) if k % a.nshards == a.shard]
    aggs, got = {}, []
    for s in syms:
        try:
            raw = _load(m, s, a.period, a.interval)
            if raw is None or len(raw) < 120:
                continue
            run_symbol(er.prep(raw), a.interval, aggs)
            got.append(s)
        except Exception as ex:  # noqa: BLE001
            print("ERROR", s, ex, file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    json.dump({"fetched": len(got), "universe": len(syms), "interval": a.interval, "aggs": aggs,
               **up.shard_meta(syms, got, a.pin_file or None, a.pin_tolerance)},
              open(os.path.join(a.out, f"ge11_{a.shard}.json"), "w"))
    print(f"shard {a.shard}: fetched {len(got)}/{len(syms)}, cells {len(aggs)}")


def verdicts(rows, floor):
    by = {r["tag"]: r for r in rows}
    out = []
    for t, r in by.items():
        if is_seg_tag(t):
            continue
        oos, bear, bull = (by.get(seg_tag(t, s)) or {} for s in ("oos", "bear", "bull"))

        def ge(x):
            return x is not None and x >= floor
        ok = (ge(r.get("pfnet")) and ge(oos.get("pfnet")) and ge(r.get("pfnet_trim5")) and ge(oos.get("pfnet_trim5"))
              and oos.get("n", 0) >= MIN_OOS_N)
        out.append({"tag": t, "confirmed": bool(ok), "pfnet": r.get("pfnet"), "trim5": r.get("pfnet_trim5"),
                    "oos_n": oos.get("n", 0), "oos_pfnet": oos.get("pfnet"), "oos_trim5": oos.get("pfnet_trim5"),
                    "bull_pfnet": bull.get("pfnet"), "bear_n": bear.get("n", 0), "bear_pfnet": bear.get("pfnet"),
                    "raw_n": r.get("raw_n"), "kept_n": r.get("n")})
    return out


def merge(path):
    import strategy_registry as sr
    merged, parts, fetched = {}, [], 0
    for f in sorted(glob.glob(os.path.join(path, "**", "ge11_*.json"), recursive=True)):
        d = json.load(open(f))
        parts.append(d)
        fetched += d.get("fetched", 0)
        for tag, ag in d["aggs"].items():
            dst = merged.setdefault(tag, new_agg())
            er.merge_aggs(dst, ag)
            dst["raw_n"] += ag.get("raw_n", 0)
    rows = [{"tag": t, **er.summarize(a), "raw_n": a["raw_n"]} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "fetched_symbols": up.merge_fetched(parts),
            "cost_round_trip": er.COST_ROUND_TRIP, "floor": sr.PFNET_LIVE_FLOOR, "rows": rows,
            "verdicts": verdicts(rows, sr.PFNET_LIVE_FLOOR)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--interval", default="1d", choices=sorted(PERIODS))
    r.add_argument("--period", default="")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=8)
    r.add_argument("--out", default="out")
    up.add_args(r)
    mg = sub.add_parser("merge")
    mg.add_argument("path")
    mg.add_argument("--json")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        a.period = a.period or PERIODS[a.interval]
        shard(a)
        return 0
    res = merge(a.path)
    print(f"fetched: {res['symbols_fetched']}  cost: {res['cost_round_trip']}  floor: {res['floor']}")
    for v in res["verdicts"]:
        print(("CONFIRMED " if v["confirmed"] else "no        ") + json.dumps(v))
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
