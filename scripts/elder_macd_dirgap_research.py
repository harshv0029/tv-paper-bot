#!/usr/bin/env python3
"""Elder research part 2 (backlog B-582, B-583, B-584, B-585, B-588, B-589, B-591, B-592,
B-594, B-595, B-596, B-597). Research only: no live wiring, no main.py edits.

Reuses the simulator and helpers of scripts/elder_indicators_research.py (stop on every trade,
ATR-multiple sweep 1.5/2/3, 0.8% round-trip cost, next-bar-open entry, 30-bar max hold, BOTH
directions, full universe via main._load_nse_universe_from_file()). Daily bars first; other
candle sizes are an --interval/--period change (bar-count constants change meaning, owed sweep).

Families (one workflow job each):
  macd    B-582 cross (12/26/9, 8/17/9, 19/39/9) | B-583 histogram slope tick | B-584 zero-line
          exhaustion tick | B-585 regular divergence (pivot-confirmed, w=3)
  dirsys  B-588/589 Directional entry (+DI13/-DI13, ADX rising on/off) | B-591 dull-market gate
          (ADX below both DI = stand aside) | B-592 overheat exit (ADX above both DI turns down)
  gaps    B-594 breakaway (vol mult 1.5/2/2.5) | B-595 continuation (trend + vol>=1.5x)
          | B-596 exhaustion-gap fade (N=3/4/5 bars without new extreme) | B-597 common-gap fade

Usage:
  python3 scripts/elder_macd_dirgap_research.py --family macd --shard 0 --nshards 4 --out out/
  python3 scripts/elder_macd_dirgap_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import research_interval as ri  # noqa: E402  (B-873: interval=4h = 1h resampled per NSE session)
import elder_indicators_research as er  # noqa: E402
import universe_pin as up  # noqa: E402

FAMILIES = ("macd", "dirsys", "gaps")


def _pack(df, long, short, ex_l, ex_s):
    def f(x):
        return np.asarray(pd.Series(x).fillna(False), dtype=bool)
    return er._pack(df, f(long), f(short), f(ex_l), f(ex_s))


# ---------------------------------------------------------------- MACD family
def _macd(df, fast, slow, sig):
    m = er.ema(df["Close"], fast) - er.ema(df["Close"], slow)
    s = er.ema(m, sig)
    return m, s, m - s


def v_macd_cross(df, fast=12, slow=26, sig=9):
    m, s, _ = _macd(df, fast, slow, sig)
    up, dn = (m > s) & (m.shift(1) <= s.shift(1)), (m < s) & (m.shift(1) >= s.shift(1))
    return _pack(df, up, dn, dn, up)


def v_macd_tick(df, zero_filter=False):
    _, _, h = _macd(df, 12, 26, 9)
    up = (h > h.shift(1)) & (h.shift(1) <= h.shift(2))
    dn = (h < h.shift(1)) & (h.shift(1) >= h.shift(2))
    if zero_filter:
        up, dn = up & (h < 0), dn & (h > 0)
    return _pack(df, up, dn, dn, up)


def v_macd_div(df, w=3):
    """Regular divergence: confirmed pivot lows (highs) of close, price makes lower low (higher
    high) while the histogram makes a shallower low (lower high) than at the previous pivot.
    Signal fires on the bar the pivot is confirmed (w bars later) - no look-ahead."""
    c = df["Close"].to_numpy(float)
    _, _, hs = _macd(df, 12, 26, 9)
    h = hs.to_numpy()
    n = len(c)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    pl = ph = None
    for i in range(w, n - w):
        win = c[i - w:i + w + 1]
        conf = i + w
        if c[i] == win.min() and not np.isnan(h[i]):
            if pl is not None and c[i] < c[pl] and h[i] > h[pl] and h[i] < 0:
                long[conf] = True
            pl = i
        if c[i] == win.max() and not np.isnan(h[i]):
            if ph is not None and c[i] > c[ph] and h[i] < h[ph] and h[i] > 0:
                short[conf] = True
            ph = i
    z = np.zeros(n, bool)
    return _pack(df, long, short, z, z)


# ---------------------------------------------------------------- Directional system
def v_dirsys(df, adx_rise=True, dull_gate=False, overheat=False):
    adx, p, m = er.adx_di(df)
    rising = adx > adx.shift(1)
    long = (p > m) & (p.shift(1) <= m.shift(1))
    short = (m > p) & (m.shift(1) <= p.shift(1))
    if adx_rise:                       # B-589
        long, short = long & rising, short & rising
    if dull_gate:                      # B-591: ADX below both DIs or falling ADX = stand aside
        trending = (adx > pd.concat([p, m], axis=1).min(axis=1)) & rising
        long, short = long & trending, short & trending
    ex_l, ex_s = m > p, p > m
    if overheat:                       # B-592: ADX above both DIs then turns down
        oh = (adx > p) & (adx > m) & (adx < adx.shift(1)) & (adx.shift(1) >= adx.shift(2))
        ex_l, ex_s = ex_l | oh, ex_s | oh
    return _pack(df, long, short, ex_l, ex_s)


# ---------------------------------------------------------------- Gaps
def _gap_state(df, vmult):
    h, l, c, v = (df[k] for k in ("High", "Low", "Close", "Volume"))
    gap_up = l > h.shift(1)
    gap_dn = h < l.shift(1)
    vavg = v.shift(1).rolling(5).mean()
    return h, l, c, gap_up, gap_dn, (v >= vmult * vavg)


def v_gap_breakaway(df, vmult=2.0):
    h, l, c, gu, gd, vol = _gap_state(df, vmult)
    long, short = gu & vol, gd & vol
    # "valid only if several consecutive new highs follow": exit after 3 bars of no new extreme
    ex_l = (h < h.shift(1)) & (h.shift(1) < h.shift(2)) & (h.shift(2) < h.shift(3))
    ex_s = (l > l.shift(1)) & (l.shift(1) > l.shift(2)) & (l.shift(2) > l.shift(3))
    return _pack(df, long, short, ex_l, ex_s)


def v_gap_continuation(df, vmult=1.5):
    h, l, c, gu, gd, vol = _gap_state(df, vmult)
    sma = c.rolling(50).mean()
    up_tr = (c > sma) & (sma > sma.shift(5))
    dn_tr = (c < sma) & (sma < sma.shift(5))
    return _pack(df, gu & vol & up_tr, gd & vol & dn_tr, c < sma, c > sma)


def v_gap_fade(df, nbars=4, vmult=1.5, exhaustion=True):
    """Fade an upside gap (short) / downside gap (long) once price stalls for nbars.
    exhaustion=True: gap on high volume; False: common gap on below-average volume.
    Cover once the opposite extreme is not extended (Elder cover rule)."""
    h, l, c, gu, gd, vol = _gap_state(df, vmult)
    n = len(df)
    hh, ll = h.to_numpy(), l.to_numpy()
    gu_a = (gu & (vol if exhaustion else ~vol)).to_numpy()
    gd_a = (gd & (vol if exhaustion else ~vol)).to_numpy()
    short, long = np.zeros(n, bool), np.zeros(n, bool)
    for i in np.flatnonzero(gu_a):
        j = i + nbars
        if j < n and hh[i + 1:j + 1].max() <= hh[i]:
            short[j] = True
    for i in np.flatnonzero(gd_a):
        j = i + nbars
        if j < n and ll[i + 1:j + 1].min() >= ll[i]:
            long[j] = True
    return _pack(df, long, short, h < h.shift(1), l > l.shift(1))


def variant_specs(family):
    S = []
    if family == "macd":
        for f, s, g in ((12, 26, 9), (8, 17, 9), (19, 39, 9)):
            S.append(("cross", {"f": f, "s": s, "g": g},
                      lambda d, f=f, s=s, g=g: v_macd_cross(d, f, s, g), {}))
        S.append(("hist_tick", {"zf": 0}, lambda d: v_macd_tick(d, False), {}))
        S.append(("hist_exhaust", {"zf": 1}, lambda d: v_macd_tick(d, True), {}))
        S.append(("hist_div", {"w": 3}, lambda d: v_macd_div(d, 3), {}))
    elif family == "dirsys":
        S.append(("cross_adxrise", {"gate": 0, "oh": 0}, lambda d: v_dirsys(d, True, False, False), {}))
        S.append(("cross_noadx", {"gate": 0, "oh": 0}, lambda d: v_dirsys(d, False, False, False), {}))
        S.append(("cross_dullgate", {"gate": 1, "oh": 0}, lambda d: v_dirsys(d, True, True, False), {}))
        S.append(("cross_overheat", {"gate": 0, "oh": 1}, lambda d: v_dirsys(d, True, False, True), {}))
    elif family == "gaps":
        for vm in (1.5, 2.0, 2.5):
            S.append(("breakaway", {"vm": vm}, lambda d, vm=vm: v_gap_breakaway(d, vm), {}))
        S.append(("continuation", {"vm": 1.5}, lambda d: v_gap_continuation(d, 1.5), {}))
        for nb in (3, 4, 5):
            S.append(("exhaust_fade", {"nb": nb}, lambda d, nb=nb: v_gap_fade(d, nb, 1.5, True), {}))
            S.append(("common_fade", {"nb": nb}, lambda d, nb=nb: v_gap_fade(d, nb, 1.5, False), {}))
    else:
        raise ValueError(family)
    return S


def run_symbol(df, family, tf, aggs):
    for variant, params, fn, mgmt in variant_specs(family):
        try:
            sig = fn(df)
        except Exception as ex:
            print("VARIANT ERROR", family, variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag(family, variant, direction, tf, {**params, "atr": am})
                er.add_trades(aggs.setdefault(tag, er.new_agg()),
                              er.simulate(df, sig, direction, am, mgmt))


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = up.select_universe(m._load_nse_universe_from_file(), args.pin_file)
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, fetched, got = {}, 0, []
    for s in syms:
        try:
            raw = ri.fetch_interval(m, s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            df = er.prep(raw)
            fetched += 1
            got.append(s)
            run_symbol(df, args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched,
               "universe": len(syms), "aggs": aggs,
               **up.shard_meta(syms, got, args.pin_file, args.pin_tolerance)},
              open(os.path.join(args.out, f"{args.family}_{args.shard}.json"), "w"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=FAMILIES)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    up.add_args(ap)
    args = ap.parse_args(argv)
    if args.merge:
        return er.main(["--merge", args.merge] + (["--json", args.json] if args.json else []))
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
