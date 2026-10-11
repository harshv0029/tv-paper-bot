#!/usr/bin/env python3
"""Elder chart-pattern, bar and trendline research (backlog B-600, B-601, B-602, B-603, B-571,
B-608, B-609, B-610, B-611, B-612, B-613, B-614, B-615, B-616, B-617, B-618, B-619, B-620,
B-621, B-622, B-624, B-607, B-623). Research only: no live wiring, no main.py edits.

Reuses the simulator of scripts/elder_indicators_research.py (stop on EVERY trade, ATR multiple
sweep 1.5/2/3, 0.8% round-trip cost, next-bar-open entry, 30-bar max hold). BOTH directions are
produced from ONE long-orientation detector run on the reciprocal-price mirror (o'=1/o, h'=1/l,
l'=1/h, c'=1/c) so long and short can never drift apart. Full universe via
main._load_nse_universe_from_file(). Daily bars by default; --interval/--period re-runs other
candle sizes (bar-count constants change meaning with the interval; 4h needs a 1h resample, owed).

Families (one workflow job each):
  reversal  B-600 island reversal | B-613/B-614 head-and-shoulders top/bottom (neckline break)
            | B-615 Hound of the Baskervilles (failed H&S, trade the opposite way) | B-618 double
            top/bottom (tol 1%/2%) | B-619 Sperandeo 1-2-3 | B-624 tail rejection
  consol    B-616 rectangle (breakout and border fade) | B-611/B-612 ascending/descending/
            symmetrical triangle breakout, volume confirm off/on (B-610) | B-617 flag breakout
            | B-609 breakout fade (N bars back inside) | B-608 congestion-edge S/R bounce
  bars      B-602 close-location | B-603/B-571 quiet-bar entry, wild-bar exit | B-601 weekday
            seasonality (buy Mon/Tue exit Thu/Fri, daily only)
  trendline B-620 trendline break close-valid (+retest) | B-621 steep (>0.5 ATR/bar) vs shallow
            break | B-622 regression-channel half/quarter entries

Usage:
  python3 scripts/elder_patterns_research.py --family reversal --shard 0 --nshards 4 --out out/
  python3 scripts/elder_patterns_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import b5_merge  # noqa: E402

FAMILIES = ("reversal", "consol", "bars", "trendline")


# ------------------------------------------------------------------ helpers
def flip(df):
    """Reciprocal-price mirror: a long pattern on the mirror is the short pattern on df."""
    m = pd.DataFrame(index=df.index)
    m["Open"], m["High"], m["Low"], m["Close"] = 1 / df["Open"], 1 / df["Low"], 1 / df["High"], 1 / df["Close"]
    m["Volume"] = df["Volume"]
    return m


def _b(x, n):
    a = np.zeros(n, bool)
    if x is not None:
        a[:] = np.asarray(pd.Series(x).fillna(False), dtype=bool)
    return a


def both(det):
    """det(df) -> (entry, exit) arrays in the LONG orientation; builds the full signal dict."""
    def f(df):
        n = len(df)
        le, lx = det(df)
        se, sx = det(flip(df))
        return er._pack(df, _b(le, n), _b(se, n), _b(lx, n), _b(sx, n))
    return f


def both_x(det):
    """det(df) -> (entry, exit, extras), extras = {'tgt': arr, 'sr': arr} price arrays in the LONG
    orientation; the short side runs on the reciprocal mirror and its price arrays are un-flipped (1/x)."""
    def f(df):
        n = len(df)
        le, lx, lxt = det(df)
        se, sx, sxt = det(flip(df))
        sig = er._pack(df, _b(le, n), _b(se, n), _b(lx, n), _b(sx, n))
        for k in ("tgt", "sr"):
            if k in lxt:
                sig["long_" + k] = np.asarray(lxt[k], float)
                with np.errstate(divide="ignore", invalid="ignore"):
                    sig["short_" + k] = 1.0 / np.asarray(sxt[k], float)
        return sig
    return f


def pivots(x, w, high=True):
    """Pivot indices (confirmed w bars later). Returns list of (idx, conf_idx)."""
    n, out = len(x), []
    for i in range(w, n - w):
        win = x[i - w:i + w + 1]
        if np.isnan(x[i]):
            continue
        if (high and x[i] == win.max()) or ((not high) and x[i] == win.min()):
            out.append((i, i + w))
    return out


def _exit_ema(df):
    e = er.ema(df["Close"], 13)
    return (df["Close"] < e) & (e < e.shift(1))


# ------------------------------------------------------------------ reversal family
def d_island(df, within=8):
    h, l = df["High"].to_numpy(), df["Low"].to_numpy()
    n = len(df)
    ent = np.zeros(n, bool)
    for i in range(1, n):                       # long island bottom: gap DOWN at i, gap UP at j
        if h[i] < l[i - 1]:
            for j in range(i + 1, min(n, i + within + 1)):
                if l[j] > h[j - 1] and l[j] > h[i]:
                    ent[j] = True
                    break
    return ent, _exit_ema(df).to_numpy()


def _hs_core(df, w, tol, hound=False):
    """Inverse head-and-shoulders (long orientation = bottom): three pivot lows, head lowest,
    shoulders within tol; neckline = max of the two intervening highs; entry on first close
    above the neckline within 20 bars of the right shoulder. hound=True: the FAILURE of a
    top, i.e. long when price closes above the head of an H&S top after breaking its neckline."""
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n = len(df)
    ent = np.zeros(n, bool)
    pl = pivots(l, w, high=False)
    for k in range(2, len(pl)):
        (i1, _), (i2, _), (i3, c3) = pl[k - 2], pl[k - 1], pl[k]
        if not (l[i2] < l[i1] and l[i2] < l[i3]):
            continue
        if abs(l[i3] - l[i1]) / l[i1] > tol:
            continue
        neck = max(h[i1:i2 + 1].max(), h[i2:i3 + 1].max())
        for j in range(c3, min(n, c3 + 20)):
            if c[j] > neck:
                ent[j] = True
                break
    return ent


def d_hs(df, w=4, tol=0.04):
    return _hs_core(df, w, tol), _exit_ema(df).to_numpy()


def d_hound(df, w=4, tol=0.04):
    """Hound of the Baskervilles: mirror H&S TOP fails (close above its head) -> long. Computed
    on the flipped frame so a 'bottom' there is a top here, then price must exceed the head."""
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n = len(df)
    ent = np.zeros(n, bool)
    ph = pivots(h, w, high=True)
    for k in range(2, len(ph)):
        (i1, _), (i2, _), (i3, c3) = ph[k - 2], ph[k - 1], ph[k]
        if not (h[i2] > h[i1] and h[i2] > h[i3]) or abs(h[i3] - h[i1]) / h[i1] > tol:
            continue
        neck = min(l[i1:i2 + 1].min(), l[i2:i3 + 1].min())
        broke = False
        for j in range(c3, min(n, c3 + 25)):
            if c[j] < neck:
                broke = True
            if broke and c[j] > h[i2]:
                ent[j] = True
                break
    return ent, _exit_ema(df).to_numpy()


def d_double(df, tol=0.02, w=4):
    """Double bottom: two pivot lows within tol, rally between >= 3%; entry close above the
    intervening high."""
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n = len(df)
    ent = np.zeros(n, bool)
    pl = pivots(l, w, high=False)
    for k in range(1, len(pl)):
        (i1, _), (i2, c2) = pl[k - 1], pl[k]
        if abs(l[i2] - l[i1]) / l[i1] > tol or i2 - i1 < 5:
            continue
        mid = h[i1:i2 + 1].max()
        if mid < l[i1] * 1.03:
            continue
        for j in range(c2, min(n, c2 + 20)):
            if c[j] > mid:
                ent[j] = True
                break
    return ent, _exit_ema(df).to_numpy()


def d_123(df, w=3):
    """Sperandeo 1-2-3 bottom: lower pivot low A, higher pivot high B, then a HIGHER pivot low C
    (failure to make a new low); entry on the close above B."""
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n = len(df)
    ent = np.zeros(n, bool)
    pl, ph = pivots(l, w, False), pivots(h, w, True)
    for ia, _ in pl:
        bs = [(ib, cb) for ib, cb in ph if ib > ia]
        if not bs:
            continue
        ib, _ = bs[0]
        cs = [(ic, cc) for ic, cc in pl if ic > ib]
        if not cs:
            continue
        ic, cc = cs[0]
        if l[ic] > l[ia] and cc < n:
            for j in range(cc, min(n, cc + 15)):
                if c[j] > h[ib]:
                    ent[j] = True
                    break
    return ent, _exit_ema(df).to_numpy()


def d_tail(df, ratio=2.0):
    o, h, l, c = (df[k] for k in ("Open", "High", "Low", "Close"))
    body = (c - o).abs().replace(0, np.nan)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    rng = (h - l).replace(0, np.nan)
    ent = (lower >= ratio * body) & (lower / rng >= 0.6) & (l <= l.shift(1).rolling(20).min())
    return ent, _exit_ema(df)


# ------------------------------------------------------------------ consolidation family
def d_rectangle(df, mode="breakout", look=20, k=6.0):
    h, l, c = df["High"], df["Low"], df["Close"]
    a = er.atr(df)
    top, bot = h.shift(1).rolling(look).max(), l.shift(1).rolling(look).min()
    tight = (top - bot) <= k * a
    if mode == "breakout":
        ent = tight & (c > top)
    else:                                       # fade the lower border, stop just outside
        ent = tight & (l <= bot + 0.25 * a) & (c > bot)
    mid = (top + bot) / 2
    ex = (c > top) if mode == "fade" else (c < mid)
    return ent, ex


def d_triangle(df, kind="asc", vol=False, look=20, tol=0.02):
    h, l, c, v = df["High"], df["Low"], df["Close"], df["Volume"]
    x = np.arange(look, dtype=float)

    def slope(s):
        return s.rolling(look).apply(lambda y: np.polyfit(x, y, 1)[0] * look / y.mean(), raw=True)
    sh, sl = slope(h), slope(l)
    top = h.shift(1).rolling(look).max()
    if kind == "asc":
        shape = (sh.abs() < tol) & (sl > tol)
    elif kind == "sym":
        shape = (sh < -tol) & (sl > tol)
    else:                                       # "desc" -> in the long orientation: flat bottom,
        shape = (sl.abs() < tol) & (sh < -tol)  # falling top, upside breakout (reversal long)
    ent = shape & (c > top)
    if vol:
        ent = ent & (v >= 1.5 * v.shift(1).rolling(5).mean())
    return ent, _exit_ema(df)


def d_flag(df, k=6, pole_atr=4.0):
    c, h = df["Close"], df["High"]
    a = er.atr(df)
    pole = (c.shift(k) - c.shift(k + 10)) >= pole_atr * a
    drift = c <= c.shift(k)                     # flag drifts against the pole
    brk = c > h.shift(1).rolling(k).max()
    return pole & drift & brk, _exit_ema(df)


def d_brk_fade(df, nb=3, look=20):
    """Breakout fade (short orientation mirrored by flip): long entry = a DOWNSIDE breakout that
    closes back above the broken low within nb bars."""
    c, l = df["Close"].to_numpy(float), df["Low"].to_numpy(float)
    low_lvl = pd.Series(l).shift(1).rolling(look).min().to_numpy()
    n = len(df)
    ent = np.zeros(n, bool)
    for i in range(look + 1, n - nb):
        if c[i] < low_lvl[i]:
            for j in range(i + 1, i + nb + 1):
                if c[j] > low_lvl[i]:
                    ent[j] = True
                    break
    return ent, _exit_ema(df).to_numpy()


def d_edge_bounce(df, look=30, band=0.01):
    """Support from congestion-area EDGES (median of the lowest decile of closes), not wicks."""
    c, l = df["Close"], df["Low"]
    edge = c.shift(1).rolling(look).quantile(0.1)
    ent = (l <= edge * (1 + band)) & (df["Close"] > edge) & (df["Close"] > df["Open"])
    return ent, _exit_ema(df)


# ------------------------------------------------------------------ bars family
def d_closeloc(df, thr=0.7, mode="follow"):
    h, l, c, o = (df[k] for k in ("High", "Low", "Close", "Open"))
    rng = (h - l).replace(0, np.nan)
    clv = (2 * c - h - l) / rng
    e = er.ema(c, 13)
    up = e > e.shift(1)
    if mode == "follow":
        ent = (clv >= thr) & (c > o) & up
    else:                                       # contrarian: bears closed bar at low in an uptrend
        ent = (clv <= -thr) & (c < o) & up
    return ent, _exit_ema(df)


def d_quiet(df, q=0.5, w=2.0):
    h, l, c, o = (df[k] for k in ("High", "Low", "Close", "Open"))
    rng = h - l
    avg = rng.rolling(20).mean().shift(1)
    e = er.ema(c, 13)
    ent = (rng <= q * avg) & (e > e.shift(1)) & (c > e)
    wild = (rng >= w * avg) & (c > o)
    return ent, wild


def d_weekday(df, entry_dow=(0, 1), exit_dow=(3, 4)):
    dow = pd.Series(df.index.dayofweek, index=df.index)
    e = er.ema(df["Close"], 13)
    ent = dow.isin(entry_dow) & (e > e.shift(1))
    return ent, dow.isin(exit_dow)


# ------------------------------------------------------------------ trendline family
def d_tl_break(df, retest=False, steep=0, w=4):
    """Long: downtrend line through the last two pivot highs; valid break = CLOSE above the
    projected line. steep=1: line slope steeper than 0.5 ATR/bar only; steep=-1: shallower only."""
    c, h = df["Close"].to_numpy(float), df["High"].to_numpy(float)
    a = er.atr(df).to_numpy()
    n = len(df)
    ent = np.zeros(n, bool)
    ph = pivots(h, w, True)
    for k in range(1, len(ph)):
        (i1, _), (i2, c2) = ph[k - 1], ph[k]
        if h[i2] >= h[i1] or i2 - i1 < 3:
            continue
        sl = (h[i2] - h[i1]) / (i2 - i1)
        if np.isnan(a[i2]):
            continue
        steepness = -sl / a[i2]
        if (steep == 1 and steepness < 0.5) or (steep == -1 and steepness >= 0.5):
            continue
        nxt = ph[k + 1][0] if k + 1 < len(ph) else n
        for j in range(c2, min(n, nxt + 1, c2 + 40)):
            line = h[i2] + sl * (j - i2)
            if c[j] > line:
                if not retest:
                    ent[j] = True
                else:
                    for m in range(j + 1, min(n, j + 6)):
                        if abs(c[m] - (h[i2] + sl * (m - i2))) <= 0.5 * a[m] and c[m] > c[m - 1]:
                            ent[m] = True
                            break
                break
    return ent, _exit_ema(df).to_numpy()


def d_tl_break_mm(df, w=4, mult=1.0):
    """B-623 measured move: after a CLOSE above the descending trendline, target = line value at the
    break bar + mult * (max vertical distance from the line to the lows since the 2nd pivot high).
    Returns (entry, exit, {'tgt': per-entry target price})."""
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n = len(df)
    a = er.atr(df).to_numpy()
    ent, tgt = np.zeros(n, bool), np.full(n, np.nan)
    ph = pivots(h, w, True)
    for k in range(1, len(ph)):
        (i1, _), (i2, c2) = ph[k - 1], ph[k]
        if h[i2] >= h[i1] or i2 - i1 < 3 or np.isnan(a[i2]):
            continue
        sl = (h[i2] - h[i1]) / (i2 - i1)
        nxt = ph[k + 1][0] if k + 1 < len(ph) else n
        for j in range(c2, min(n, nxt + 1, c2 + 40)):
            line = h[i2] + sl * (j - i2)
            if c[j] > line:
                seg = np.arange(i2, j + 1)
                dist = (h[i2] + sl * (seg - i2) - l[seg]).max()
                if dist > 0:
                    ent[j], tgt[j] = True, line + mult * dist
                break
    return ent, _exit_ema(df).to_numpy(), {"tgt": tgt}


def d_edge_bounce_sr(df, look=30, band=0.01):
    """B-607 support-bounce long whose S/R level for stop-tightening is the congestion TOP edge
    (90th pct of prior closes). Returns (entry, exit, {'sr': level})."""
    ent, ex = d_edge_bounce(df, look, band)
    top = df["Close"].shift(1).rolling(look).quantile(0.9)
    return ent.to_numpy(), ex.to_numpy(), {"sr": top.to_numpy()}


def d_channel(df, look=30, zone=0.25):
    c = df["Close"]
    x = np.arange(look, dtype=float)
    mid_slope = c.rolling(look).apply(lambda y: np.polyfit(x, y, 1)[0], raw=True)
    mid_end = c.rolling(look).apply(lambda y: np.polyval(np.polyfit(x, y, 1), look - 1), raw=True)
    sd = c.rolling(look).std()
    pos = (c - (mid_end - 2 * sd)) / (4 * sd).replace(0, np.nan)
    ent = (mid_slope > 0) & (pos <= zone) & (c > c.shift(1))
    return ent, (pos >= 0.9)


def variant_specs(family):
    S = []
    if family == "reversal":
        S.append(("island", {"within": 8}, both(d_island), {}))
        for tol in (0.03, 0.05):
            S.append(("hs_neckline", {"tol": tol}, both(lambda d, t=tol: d_hs(d, 4, t)), {}))
            S.append(("hound", {"tol": tol}, both(lambda d, t=tol: d_hound(d, 4, t)), {}))
        for tol in (0.01, 0.02):
            S.append(("double", {"tol": tol}, both(lambda d, t=tol: d_double(d, t)), {}))
        S.append(("sperandeo123", {"w": 3}, both(d_123), {}))
        for r in (1.5, 2.0):
            S.append(("tail", {"ratio": r}, both(lambda d, r=r: d_tail(d, r)), {}))
    elif family == "consol":
        for mode in ("breakout", "fade"):
            S.append((f"rect_{mode}", {"k": 6.0}, both(lambda d, m=mode: d_rectangle(d, m)), {}))
        for kind in ("asc", "sym", "desc"):
            for vol in (False, True):
                S.append((f"tri_{kind}", {"vol": int(vol)}, both(lambda d, k=kind, v=vol: d_triangle(d, k, v)), {}))
        for k in (5, 8):
            S.append(("flag", {"k": k}, both(lambda d, k=k: d_flag(d, k)), {}))
        for nb in (2, 3, 5):
            S.append(("brk_fade", {"nb": nb}, both(lambda d, nb=nb: d_brk_fade(d, nb)), {}))
        S.append(("edge_bounce", {"look": 30}, both(d_edge_bounce), {}))
        for sra in (0.5, 1.0):      # B-607: tighten stop to a 1-ATR trail once within sra ATR of the top edge
            S.append(("edge_bounce_srtight", {"look": 30, "sra": sra}, both_x(d_edge_bounce_sr),
                      {"sr_atr": sra, "sr_trail_atr": 1.0}))
    elif family == "bars":
        for thr in (0.6, 0.8):
            for mode in ("follow", "contra"):
                S.append((f"closeloc_{mode}", {"thr": thr}, both(lambda d, t=thr, m=mode: d_closeloc(d, t, m)), {}))
        for q in (0.4, 0.5, 0.7):
            S.append(("quiet_wild", {"q": q}, both(lambda d, q=q: d_quiet(d, q)), {}))
        S.append(("weekday", {"ent": 1, "ex": 4}, both(d_weekday), {}))
    elif family == "trendline":
        for steep in (0, 1, -1):
            for rt in (0, 1):
                S.append(("tl_break", {"steep": steep, "retest": rt},
                          both(lambda d, s=steep, r=rt: d_tl_break(d, bool(r), s)), {}))
        for mult in (1.0, 0.5):
            S.append(("tl_break_mm", {"mult": mult}, both_x(lambda d, m=mult: d_tl_break_mm(d, 4, m)), {}))
        for z in (0.25, 0.5):
            S.append(("channel", {"zone": z}, both(lambda d, z=z: d_channel(d, 30, z)), {}))
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
                er.add_trades(aggs.setdefault(tag, er.new_agg()), er.simulate(df, sig, direction, am, mgmt))


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
            fetched += 1
            run_symbol(er.prep(raw), args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched, "universe": len(syms),
               "aggs": aggs}, open(os.path.join(args.out, f"{args.family}_{args.shard}.json"), "w"))


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
    args = ap.parse_args(argv)
    if args.merge:
        return b5_merge.merge_main(args.merge, args.json)
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
