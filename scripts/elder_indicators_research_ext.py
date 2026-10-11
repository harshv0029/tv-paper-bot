#!/usr/bin/env python3
"""Elder "Trading for a Living" indicator research, second batch (extends
scripts/elder_indicators_research.py; reuses its simulator, aggregation and naming).

Research only: no live wiring, no main.py edits. Every variant runs BOTH directions
with a stop-loss on every trade (ATR sweep 1.5/2/3), 0.8% round-trip cost, entry at
the next bar (open, or a buy-stop level for force_index), 30-bar max hold.

Families (one workflow job each) and the backlog rows they cover:
  williams_r   B-647 B-648 B-649 B-764   %R(7) 10/90 lines, divergence, failure swing
  stoch_slow   B-650 B-652 B-654 B-655 B-765  Slow Stoch(5,3,3) oversold turn, divergence, pop, direction
  rsi          B-658 B-659 B-660          RSI(7/14) Wilder 30/70 cross-back, divergence
  volume       B-625 B-626 B-663 B-664 B-665  low-volume pullback, climax retest, 5d volume-MA filter
  ad_line      B-668 B-669                A/D (Williams) and Volume Accumulator confirm/diverge/breakout
  force_index  B-697 B-698 B-699 B-763    FI2 pullback + buy-stop entry, FI13 zero-line cross
  macdh        B-723 B-761 B-675 B-769    MACD-H slope turn (below/above zero), divergence, seasons
  channel      B-716 B-717 B-718 B-719 B-766  EMA13 envelope fade vs breakout-follow, highs/lows channel
  parabolic    B-705                      Wilder SAR flip entries, flip exit
  profit_protect B-738 B-739 B-770        break-even after k*ATR(14) (ADR proxy) and fraction-of-best-profit
                                          trail, on the EMA13-dip entry (entry held constant, exit isolated)

Tags: <family>__<variant>__<dir>__<tf>__<params>__v1.

Usage:
  python3 scripts/elder_indicators_research_ext.py --family rsi --shard 0 --nshards 4 --out out/
  python3 scripts/elder_indicators_research_ext.py --merge out/ --json merged.json
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

FAMILIES = ("williams_r", "stoch_slow", "rsi", "volume", "ad_line", "force_index",
            "macdh", "channel", "parabolic", "profit_protect")


# ---------------------------------------------------------------- indicators

def williams_r(df, n=7):
    hh, ll = df["High"].rolling(n).max(), df["Low"].rolling(n).min()
    return 100 * (hh - df["Close"]) / (hh - ll).replace(0, np.nan)   # 0 = top, 100 = bottom


def stoch_slow(df, k=5, d=3, s=3):
    lo, hi = df["Low"].rolling(k).min(), df["High"].rolling(k).max()
    fast_d = (df["Close"] - lo).rolling(d).sum() / (hi - lo).rolling(d).sum().replace(0, np.nan) * 100
    return fast_d, fast_d.rolling(s).mean()          # slow %K = fast %D, slow %D


def rsi_wilder(close, n=7):
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def ad_williams(df, kind="ad"):
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    if kind == "ad":
        m = (df["Close"] - df["Open"]) / rng
    else:                                            # Chaikin volume accumulator, mean-price variant
        m = (2 * df["Close"] - df["High"] - df["Low"]) / (2 * rng)
    return (m.fillna(0.0) * df["Volume"]).cumsum()


def parabolic_sar(df, af0=0.02, afmax=0.2):
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    n = len(df)
    sar, trend = np.full(n, np.nan), np.zeros(n)
    if n < 3:
        return pd.Series(sar, index=df.index), pd.Series(trend, index=df.index)
    up, ep, af = True, h[0], af0
    s = l[0]
    sar[0], trend[0] = s, 1
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                up, s, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + af0, afmax)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                up, s, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + af0, afmax)
        sar[i], trend[i] = s, 1 if up else -1
    return pd.Series(sar, index=df.index), pd.Series(trend, index=df.index)


def _bool(x):
    return pd.Series(x).fillna(False).to_numpy(bool)


def _trend(df, n=13):
    return er._ema_state(df, n)


def _divergence(price_low, osc, lb):
    """Bullish: price makes a new lb-bar low while osc is above its prior lb-bar low."""
    new_low = price_low <= price_low.rolling(lb).min()
    return new_low & (osc > osc.shift(1).rolling(lb).min())


def _divergence_bear(price_high, osc, lb):
    new_high = price_high >= price_high.rolling(lb).max()
    return new_high & (osc < osc.shift(1).rolling(lb).max())


# ---------------------------------------------------------------- variants

def v_williams(df, mode="lines", line=10, n=7, lb=10):
    r = williams_r(df, n)                       # 0 = top, 100 = bottom
    e, up, dn = _trend(df)
    os_, ob = 100 - line, line
    if mode == "lines":                         # was oversold, turns back out of it, in up-trend
        long = up & (r.shift(1) >= os_) & (r < r.shift(1))
        short = dn & (r.shift(1) <= ob) & (r > r.shift(1))
    elif mode == "diverge":                     # price new extreme but %R extreme is weaker
        long = _divergence(df["Low"], -r, lb) & (r < r.shift(1))
        short = _divergence_bear(df["High"], -r, lb) & (r > r.shift(1))
    else:                                       # failure swing: turns mid-move without reaching the line
        long = up & (r.shift(1) > r.shift(2)) & (r < r.shift(1)) & (r.shift(1) < os_)
        short = dn & (r.shift(1) < r.shift(2)) & (r > r.shift(1)) & (r.shift(1) > ob)
    return er._pack(df, _bool(long), _bool(short), _bool(dn), _bool(up))


def v_stoch_slow(df, mode="turn", lo=20, hi=80, lb=10):
    k, d = stoch_slow(df)
    e, up, dn = _trend(df)
    if mode == "turn":                          # oversold turn in an up-trend (no wait for crossover)
        long = up & (k.shift(1) < lo) & (k > k.shift(1))
        short = dn & (k.shift(1) > hi) & (k < k.shift(1))
        ex_l, ex_s = k > hi, k < lo
    elif mode == "diverge":
        long = _divergence(df["Low"], k, lb) & (k > k.shift(1)) & (k < 50)
        short = _divergence_bear(df["High"], k, lb) & (k < k.shift(1)) & (k > 50)
        ex_l, ex_s = k > hi, k < lo
    elif mode == "pop":                         # Bernstein: cross above hi buys, turn down sells
        long = (k.shift(1) <= hi) & (k > hi)
        short = (k.shift(1) >= lo) & (k < lo)
        ex_l, ex_s = k < k.shift(1), k > k.shift(1)
    else:                                       # direction: both lines rising / falling together
        rise = (k > k.shift(1)) & (d > d.shift(1))
        fall = (k < k.shift(1)) & (d < d.shift(1))
        long, short = rise & ~rise.shift(1, fill_value=False), fall & ~fall.shift(1, fill_value=False)
        ex_l, ex_s = fall, rise
    return er._pack(df, _bool(long), _bool(short), _bool(ex_l), _bool(ex_s))


def v_rsi(df, mode="levels", n=7, lo=30, hi=70, lb=10):
    r = rsi_wilder(df["Close"], n)
    if mode == "levels":                        # dips below lo then crosses back above (mirror for short)
        long = (r.shift(1) < lo) & (r >= lo)
        short = (r.shift(1) > hi) & (r <= hi)
    else:
        long = _divergence(df["Low"], r, lb) & (r > r.shift(1))
        short = _divergence_bear(df["High"], r, lb) & (r < r.shift(1))
    return er._pack(df, _bool(long), _bool(short), _bool(r > hi), _bool(r < lo))


def v_volume(df, mode="pullback", lb=10, thr=0.25):
    v = df["Volume"]
    avg = v.rolling(lb).mean().shift(1)
    low, high = v <= avg * (1 - thr), v >= avg * (1 + thr)     # Elder: +/-25% vs ~2-week average
    e, up, dn = _trend(df)
    c = df["Close"]
    if mode == "pullback":                      # dip on shrinking volume in an up-trend = buy the end
        long = up & (c < c.shift(1)) & low
        short = dn & (c > c.shift(1)) & low
    elif mode == "climax":                      # new 20-bar extreme on high volume, retest on low volume
        cl = (df["Low"] <= df["Low"].rolling(20).min()) & high
        ch = (df["High"] >= df["High"].rolling(20).max()) & high
        recent_cl = cl.shift(1).rolling(5).max().fillna(0) > 0
        recent_ch = ch.shift(1).rolling(5).max().fillna(0) > 0
        long = recent_cl & low & (df["Low"] <= df["Low"].rolling(5).min() * 1.01)
        short = recent_ch & low & (df["High"] >= df["High"].rolling(5).max() * 0.99)
    elif mode == "ma5_confirm":                 # volume above its 5-day MA on a breakout close
        m5 = v.rolling(5).mean().shift(1)
        long = up & (v > m5) & (c > df["High"].shift(1).rolling(5).max())
        short = dn & (v > m5) & (c < df["Low"].shift(1).rolling(5).min())
    else:                                       # expand: rally bar on above-average volume after a down bar
        m5 = v.rolling(5).mean().shift(1)
        long = up & (c > c.shift(1)) & (v > m5) & (c.shift(1) < c.shift(2))
        short = dn & (c < c.shift(1)) & (v > m5) & (c.shift(1) > c.shift(2))
    return er._pack(df, _bool(long), _bool(short), _bool(dn), _bool(up))


def v_ad(df, kind="ad", mode="confirm", lb=20):
    a, c = ad_williams(df, kind), df["Close"]
    pa, pc = a.shift(1).rolling(lb).max(), c.shift(1).rolling(lb).max()
    pal, pcl = a.shift(1).rolling(lb).min(), c.shift(1).rolling(lb).min()
    if mode == "confirm":
        long, short = (c > pc) & (a > pa), (c < pcl) & (a < pal)
    elif mode == "diverge":
        short, long = (c > pc) & (a < pa), (c < pcl) & (a > pal)
    else:
        long, short = (a > pa) & (c <= pc), (a < pal) & (c >= pcl)
    e, up, dn = _trend(df)
    return er._pack(df, _bool(long), _bool(short), _bool(dn), _bool(up))


def v_force(df, mode="pullback", span=13):
    fi1 = df["Close"].diff() * df["Volume"]
    fi2, fi13 = er.ema(fi1, 2), er.ema(fi1, span)
    e, up, dn = _trend(df)
    if mode == "pullback":                      # FI2 < 0 in up-trend: buy-stop above the signal-day high
        tick = 0.05
        return er._pack(df, _bool(up & (fi2 < 0)), _bool(dn & (fi2 > 0)),
                        _bool(fi2 > 0), _bool(fi2 < 0),
                        long_lvl=(df["High"] + tick).to_numpy(),
                        short_lvl=(df["Low"] - tick).to_numpy())
    long = (fi13 > 0) & (fi13.shift(1) <= 0)    # zero-line cross
    short = (fi13 < 0) & (fi13.shift(1) >= 0)
    return er._pack(df, _bool(long), _bool(short), _bool(fi13 < 0), _bool(fi13 > 0))


def v_macdh(df, mode="slope_below", lb=10):
    h = er.macd_hist(df["Close"])
    e, up, dn = _trend(df)
    turn_up, turn_dn = h > h.shift(1), h < h.shift(1)
    first_up = turn_up & ~turn_up.shift(1, fill_value=False)
    first_dn = turn_dn & ~turn_dn.shift(1, fill_value=False)
    if mode == "slope_below":                   # turns up below the centerline (best), mirror above
        long, short = first_up & (h < 0), first_dn & (h > 0)
    elif mode == "slope_any":
        long, short = first_up, first_dn
    elif mode == "diverge":
        long = _divergence(df["Low"], h, lb) & turn_up & (h < 0)
        short = _divergence_bear(df["High"], h, lb) & turn_dn & (h > 0)
    else:                                       # seasons: spring (rising from <0) long, autumn short, EMA13 gate
        long = turn_up & (h.shift(1) < 0) & up
        short = turn_dn & (h.shift(1) > 0) & dn
    return er._pack(df, _bool(long), _bool(short), _bool(turn_dn), _bool(turn_up))


def v_channel(df, mode="fade", pct=0.02, src="close"):
    if src == "close":
        mid = er.ema(df["Close"], 13)
        up_l, lo_l = mid * (1 + pct), mid * (1 - pct)
    else:                                       # channel of EMA13 of highs / lows
        up_l, lo_l = er.ema(df["High"], 13), er.ema(df["Low"], 13)
        mid = (up_l + lo_l) / 2
    e, up, dn = _trend(df)
    if mode == "fade":                          # buy a dip to the lower line in an up-trend, short a pop
        long = up & (df["Low"] <= lo_l)
        short = dn & (df["High"] >= up_l)
        ex_l, ex_s = df["High"] >= up_l, df["Low"] <= lo_l
    else:                                       # breakout-follow (book's rejected amateur variant)
        long, short = df["Close"] > up_l, df["Close"] < lo_l
        ex_l, ex_s = df["Close"] < mid, df["Close"] > mid
    return er._pack(df, _bool(long), _bool(short), _bool(ex_l), _bool(ex_s))


def v_ema13_plain(df):
    return er.v_ema13(df, 13)


def v_sar(df, af0=0.02, afmax=0.2):
    _, t = parabolic_sar(df, af0, afmax)
    flip_up = (t == 1) & (t.shift(1) == -1)
    flip_dn = (t == -1) & (t.shift(1) == 1)
    return er._pack(df, _bool(flip_up), _bool(flip_dn), _bool(flip_dn), _bool(flip_up))


def variant_specs(family):
    """-> list of (variant, params_without_atr, fn, mgmt)."""
    S = []
    if family == "williams_r":
        for line in (10, 15, 20):
            S.append(("lines", {"line": line}, lambda d, l=line: v_williams(d, "lines", l), {}))
        for lb in (5, 10, 20):
            S.append(("diverge", {"lb": lb}, lambda d, lb=lb: v_williams(d, "diverge", lb=lb), {}))
        S.append(("failure_swing", {"line": 10}, lambda d: v_williams(d, "failure"), {}))
    elif family == "stoch_slow":
        for lo, hi in ((20, 80), (30, 70)):
            S.append(("turn", {"band": lo}, lambda d, a=lo, b=hi: v_stoch_slow(d, "turn", a, b), {}))
            S.append(("pop", {"band": hi}, lambda d, a=lo, b=hi: v_stoch_slow(d, "pop", a, b), {}))
        for lb in (5, 10, 20):
            S.append(("diverge", {"lb": lb}, lambda d, lb=lb: v_stoch_slow(d, "diverge", lb=lb), {}))
        S.append(("direction", {"band": 0}, lambda d: v_stoch_slow(d, "direction"), {}))
    elif family == "rsi":
        for n in (7, 14):
            for lo, hi in ((30, 70), (25, 75)):
                S.append(("levels", {"n": n, "band": lo},
                          lambda d, n=n, a=lo, b=hi: v_rsi(d, "levels", n, a, b), {}))
            for lb in (5, 10, 20):
                S.append(("diverge", {"n": n, "lb": lb},
                          lambda d, n=n, lb=lb: v_rsi(d, "diverge", n, lb=lb), {}))
    elif family == "volume":
        for mode in ("pullback", "climax", "ma5_confirm", "expand"):
            for lb in (10, 20):
                S.append((mode, {"lb": lb}, lambda d, m=mode, lb=lb: v_volume(d, m, lb), {}))
    elif family == "ad_line":
        for kind in ("ad", "vacc"):
            for mode in ("confirm", "diverge", "breakout"):
                for lb in (10, 20, 40):
                    S.append((f"{kind}_{mode}", {"lb": lb},
                              lambda d, k=kind, m=mode, lb=lb: v_ad(d, k, m, lb), {}))
    elif family == "force_index":
        S.append(("fi2_pullback", {"n": 13}, lambda d: v_force(d, "pullback"), {}))
        S.append(("fi13_zero_cross", {"n": 13}, lambda d: v_force(d, "zero"), {}))
        S.append(("fi2_pullback_be", {"n": 13}, lambda d: v_force(d, "pullback"),
                  {"be_atr": 1.0, "trail_frac": 0.5}))
    elif family == "macdh":
        for mode in ("slope_below", "slope_any", "seasons"):
            S.append((mode, {"lb": 0}, lambda d, m=mode: v_macdh(d, m), {}))
        for lb in (5, 10, 20):
            S.append(("diverge", {"lb": lb}, lambda d, lb=lb: v_macdh(d, "diverge", lb), {}))
    elif family == "channel":
        for pct in (0.015, 0.02, 0.03):
            for mode in ("fade", "breakout"):
                S.append((f"env_{mode}", {"pct": pct},
                          lambda d, m=mode, p=pct: v_channel(d, m, p), {}))
        for mode in ("fade", "breakout"):
            S.append((f"hilo_{mode}", {"pct": 0}, lambda d, m=mode: v_channel(d, m, 0, "hilo"), {}))
    elif family == "parabolic":
        for af0, afmax in ((0.02, 0.2), (0.015, 0.15), (0.025, 0.25)):
            S.append(("sar_flip", {"af": af0, "afmax": afmax},
                      lambda d, a=af0, b=afmax: v_sar(d, a, b), {}))
    elif family == "profit_protect":
        # entry fixed (EMA13 dip, no BE-on-EMA); only the profit-protect management varies.
        # be=0.01 means "trail from the first bar" (B-739 pure 50% rule); be=0 row is the unprotected baseline.
        S.append(("pp_baseline", {"be": 0, "tr": 0}, lambda d: v_ema13_plain(d), {}))
        for be in (0.01, 0.5, 1.0, 1.5, 2.0):
            S.append(("pp_be", {"be": be, "tr": 0}, lambda d: v_ema13_plain(d),
                      {"be_atr": be}))
            for tr in (0.4, 0.5, 0.6, 0.7):
                S.append(("pp_be_trail", {"be": be, "tr": tr}, lambda d: v_ema13_plain(d),
                          {"be_atr": be, "trail_frac": tr}))
    else:
        raise ValueError(family)
    return S


# ---------------------------------------------------------------- driver (reuses er)

def run_symbol(df, family, tf, aggs):
    for variant, params, fn, mgmt in variant_specs(family):
        try:
            sig = fn(df)
        except Exception as exc:
            print("VARIANT ERROR", family, variant, exc, file=sys.stderr)
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
            run_symbol(df, args.family, args.interval, aggs)
        except Exception as exc:
            print("ERROR", s, exc, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched,
               "universe": len(syms), "aggs": aggs},
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
    args = ap.parse_args(argv)
    if args.merge:
        return er.main(["--merge", args.merge] + (["--json", args.json] if args.json else []))
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
