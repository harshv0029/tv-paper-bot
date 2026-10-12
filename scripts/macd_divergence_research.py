#!/usr/bin/env python3
"""MACD divergence full-universe re-run + SHORT mirror, candle sweep (B-808..B-810).

Why: the three registered cells macd__hist_div__long__1d__atr{1d5,2,3}_w3__v1 (elder-macd-dirgap-research.yml
run 38145684388) were run on an unlabelled universe, daily only. This harness re-runs the same rule on the
FULL universe (main._load_nse_universe_from_file()), registers the short mirror as its own tags, and sweeps
candle size 15m / 1h / 1d and the ATR stop multiple 1.5/2/3 (stop on every trade, 0.8% round-trip cost).

No main.py function implements MACD divergence, so this is a FAITHFUL PORT of
scripts/elder_macd_dirgap_research.py::v_macd_div (flagged as a port, not a call into main.py). Parity with
the original is unit-tested for the w=3 histogram case. New family name `macddiv` keeps every tag distinct
from the registered `macd__hist_div` v1 tags (never pooled).

Variants (each its own tag, long and short, 3 ATR multiples):
  hist_zero   histogram divergence, histogram must sit on the reversal side of zero (== original rule)
  hist_any    histogram divergence, no zero-side filter
  line_any    MACD-LINE divergence (line instead of histogram), no zero filter
  each at pivot half-width w in (3, 5). Bar-count constants (w, 30-bar max hold, 12/26/9) change meaning
  with the candle size; that is stated, not hidden. 4h needs a 1h resample (owed, not built).

Usage:
  python3 scripts/macd_divergence_research.py --shard 0 --nshards 8 --interval 1h --out out/
  python3 scripts/macd_divergence_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402

FAMILY = "macddiv"
WIDTHS = (3, 5)
# interval -> default yfinance period (15m 60d, 1h 730d, 1d 5y)
PERIODS = {"15m": "60d", "1h": "730d", "1d": "5y"}


def macd_parts(df, fast=12, slow=26, sig=9):
    m = er.ema(df["Close"], fast) - er.ema(df["Close"], slow)
    s = er.ema(m, sig)
    return m, s, m - s


def v_macd_divergence(df, w=3, source="hist", zero_filter=True):
    """Regular divergence on confirmed close pivots. Price lower low + indicator higher low = long;
    price higher high + indicator lower high = short (mirror). Fires w bars after the pivot (no look-ahead).
    source: 'hist' (MACD histogram) or 'line' (MACD line)."""
    c = df["Close"].to_numpy(float)
    m, _, hs = macd_parts(df)
    h = (hs if source == "hist" else m).to_numpy(float)
    n = len(c)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    pl = ph = None
    for i in range(w, n - w):
        win = c[i - w:i + w + 1]
        conf = i + w
        if np.isnan(h[i]):
            continue
        if c[i] == win.min():
            if pl is not None and c[i] < c[pl] and h[i] > h[pl] and (h[i] < 0 or not zero_filter):
                long[conf] = True
            pl = i
        if c[i] == win.max():
            if ph is not None and c[i] > c[ph] and h[i] < h[ph] and (h[i] > 0 or not zero_filter):
                short[conf] = True
            ph = i
    z = np.zeros(n, bool)
    return er._pack(df, long, short, z, z)


def variant_specs():
    S = []
    for w in WIDTHS:
        for name, src, zf in (("hist_zero", "hist", True), ("hist_any", "hist", False),
                              ("line_any", "line", False)):
            S.append((name, {"w": w},
                      lambda d, w=w, src=src, zf=zf: v_macd_divergence(d, w, src, zf)))
    return S


def run_symbol(df, tf, aggs):
    for variant, params, fn in variant_specs():
        sig = fn(df)
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag(FAMILY, variant, direction, tf, {**params, "atr": am})
                er.add_trades(aggs.setdefault(tag, er.new_agg()), er.simulate(df, sig, direction, am, {}))


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            df = er.prep(raw)
            fetched += 1
            run_symbol(df, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"shard {args.shard} {args.interval}: fetched {fetched}/{len(syms)}, tags {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": FAMILY, "interval": args.interval, "fetched": fetched,
               "universe": len(syms), "aggs": aggs},
              open(os.path.join(args.out, f"{FAMILY}_{args.interval}_{args.shard}.json"), "w"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=8)
    ap.add_argument("--interval", default="1d", choices=sorted(PERIODS))
    ap.add_argument("--period")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        return er.main(["--merge", args.merge] + (["--json", args.json] if args.json else []))
    args.period = args.period or PERIODS[args.interval]
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
