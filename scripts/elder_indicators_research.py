#!/usr/bin/env python3
"""Elder "Trading for a Living" indicator research (backlog B-579, B-590, B-643,
B-653, B-667, B-695, B-708, B-759).

Research only: no live wiring, no main.py edits. One generic bar-by-bar simulator
runs every variant in BOTH directions with a stop-loss on every trade
(ATR-multiple sweep), a 0.8% round-trip cost, entry at the NEXT bar after the
signal (open, or a breakout level for Triple Screen), and a max-hold timeout.

Families (one workflow job each):
  ema13          B-579  EMA trend-follow, buy dip to EMA in rising EMA, BE after close above EMA
  ema_gate       B-708  EMA slope gate (length 9/13/21/26), enter on slope turn, exit on flip
  roc            B-643  RoC(n)/Momentum(n) centerline cross-back inside an EMA trend
  stoch_filter   B-653  Stochastic >80 / <20 veto overlay on the ema13 entries (with baseline)
  obv            B-667  OBV confirm / divergence / range-breakout
  elder_ray      B-695  Elder-ray entries, peak-divergence exits, bull/bear power veto
  adx_bell       B-590  directional ring-the-bell (ADX +k off its low below both DIs)
  triple_screen  B-759  weekly MACD-H slope + daily FI/Stoch/Elder-ray, buy-stop entry, BE + 50% trail

Tags follow <family>__<variant>__<dir>__<tf>__<params>__v1.

Usage:
  python3 scripts/elder_indicators_research.py --family ema13 --shard 0 --nshards 4 --out out/
  python3 scripts/elder_indicators_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

COST_ROUND_TRIP = 0.008     # 0.8% of notional, round trip
MAX_HOLD_BARS = 30
ATR_MULTS = (1.5, 2.0, 3.0)
FAMILIES = ("ema13", "ema_gate", "roc", "stoch_filter", "obv", "elder_ray",
            "adx_bell", "triple_screen")


# ---------------------------------------------------------------- naming

def _fmt(v) -> str:
    if isinstance(v, float) and not v.is_integer():
        return repr(round(v, 4)).replace(".", "d")
    return str(int(v)) if isinstance(v, (int, float)) else str(v)


def make_tag(family, variant, direction, tf, params, version=1) -> str:
    p = "_".join(f"{k}{_fmt(params[k])}" for k in sorted(params))
    return f"{family}__{variant}__{direction}__{tf}__{p}__v{version}"


# ---------------------------------------------------------------- indicators

def ema(s, n):
    return pd.Series(s).ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def adx_di(df, n=14):
    h, l = df["High"], df["Low"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * pdm.ewm(alpha=1.0 / n, adjust=False).mean() / a
    mdi = 100 * mdm.ewm(alpha=1.0 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False).mean(), pdi, mdi


def stochastic(df, k=5, d=3):
    lo, hi = df["Low"].rolling(k).min(), df["High"].rolling(k).max()
    raw = 100 * (df["Close"] - lo) / (hi - lo).replace(0, np.nan)
    return raw.rolling(d).mean()


def obv(df):
    sign = np.sign(df["Close"].diff()).fillna(0.0)
    return (sign * df["Volume"]).cumsum()


def macd_hist(close, fast=12, slow=26, sig=9):
    m = ema(close, fast) - ema(close, slow)
    return m - ema(m, sig)


def force_index2(df):
    return ema(df["Close"].diff() * df["Volume"], 2)


def weekly_hist_slope_daily(df):
    """Slope sign of the weekly MACD-H, mapped to daily bars using only COMPLETED
    prior weeks (no look-ahead). Needs a DatetimeIndex."""
    wk = df["Close"].resample("W-FRI").last().dropna()
    h = macd_hist(wk)
    slope = np.sign(h.diff()).shift(1)          # last completed week's slope
    return slope.reindex(df.index, method="ffill")


# ---------------------------------------------------------------- variants
# A variant fn(df) -> dict(long, short, long_lvl, short_lvl, exit_long, exit_short)
# long/short: bool arrays "signal on bar i close"; *_lvl: optional breakout fill level
# arrays (NaN = fill at next open); exit_*: bool arrays checked at bar close.

def _arr(x):
    return np.asarray(x, dtype=bool)


def _pack(df, long, short, exit_long, exit_short, long_lvl=None, short_lvl=None):
    n = len(df)
    nan = np.full(n, np.nan)
    return {"long": _arr(long), "short": _arr(short), "exit_long": _arr(exit_long),
            "exit_short": _arr(exit_short),
            "long_lvl": nan if long_lvl is None else np.asarray(long_lvl, float),
            "short_lvl": nan if short_lvl is None else np.asarray(short_lvl, float)}


def _ema_state(df, n):
    e = ema(df["Close"], n)
    return e, (e > e.shift(1)), (e < e.shift(1))


def v_ema13(df, n=13):
    e, up, dn = _ema_state(df, n)
    long = up & (df["Low"] <= e) & (df["Close"] > e * 0.985)
    short = dn & (df["High"] >= e) & (df["Close"] < e * 1.015)
    return _pack(df, long.fillna(False), short.fillna(False),
                 (dn & (df["Close"] < e)).fillna(False), (up & (df["Close"] > e)).fillna(False))


def v_ema_gate(df, n=13):
    e = ema(df["Close"], n)
    up2 = (e > e.shift(1)) & (e.shift(1) > e.shift(2))
    dn2 = (e < e.shift(1)) & (e.shift(1) < e.shift(2))
    long = up2 & ~up2.shift(1, fill_value=False)
    short = dn2 & ~dn2.shift(1, fill_value=False)
    return _pack(df, long.fillna(False), short.fillna(False),
                 (e < e.shift(1)).fillna(False), (e > e.shift(1)).fillna(False))


def v_roc(df, n=7, kind="roc", tn=26):
    c = df["Close"]
    x = c / c.shift(n) if kind == "roc" else c - c.shift(n)
    mid = 1.0 if kind == "roc" else 0.0
    _, up, dn = _ema_state(df, tn)
    long = up & (x.shift(1) < mid) & (x > x.shift(1))
    short = dn & (x.shift(1) > mid) & (x < x.shift(1))
    return _pack(df, long.fillna(False), short.fillna(False), dn.fillna(False), up.fillna(False))


def v_stoch_filter(df, hi=80, lo=20, n=13):
    base = v_ema13(df, n)
    if hi is None:
        return base
    st = stochastic(df, 5, 3)
    base["long"] = base["long"] & _arr(st <= hi)
    base["short"] = base["short"] & _arr(st >= lo)
    return base


def v_obv(df, mode="confirm", lb=20):
    c, o = df["Close"], obv(df)
    pc, po = c.shift(1).rolling(lb).max(), o.shift(1).rolling(lb).max()
    pcl, pol = c.shift(1).rolling(lb).min(), o.shift(1).rolling(lb).min()
    if mode == "confirm":
        long, short = (c > pc) & (o > po), (c < pcl) & (o < pol)
    elif mode == "diverge":
        # price new high but OBV below its prior peak = short; mirror = long
        short, long = (c > pc) & (o < po), (c < pcl) & (o > pol)
    else:  # breakout: OBV breaks its range while price still inside it
        long, short = (o > po) & (c <= pc), (o < pol) & (c >= pcl)
    _, up, dn = _ema_state(df, 13)
    return _pack(df, long.fillna(False), short.fillna(False), dn.fillna(False), up.fillna(False))


def v_elder_ray(df, mode="plain", lb=5):
    e, up, dn = _ema_state(df, 13)
    bull, bear = df["High"] - e, df["Low"] - e
    long = up & (bear < 0) & (bear > bear.shift(1))
    short = dn & (bull > 0) & (bull < bull.shift(1))
    ex_l, ex_s = dn & (df["Close"] < e), up & (df["Close"] > e)
    if mode == "exit_div":
        newhi = df["High"] >= df["High"].rolling(lb).max()
        newlo = df["Low"] <= df["Low"].rolling(lb).min()
        ex_l = ex_l | (newhi & (bull < bull.shift(1).rolling(lb).max()))
        ex_s = ex_s | (newlo & (bear > bear.shift(1).rolling(lb).min()))
    elif mode == "veto":
        g = v_ema_gate(df, 13)
        long = pd.Series(g["long"], index=df.index) & ~(bear > 0)
        short = pd.Series(g["short"], index=df.index) & ~(bull < 0)
    return _pack(df, long.fillna(False), short.fillna(False), ex_l.fillna(False), ex_s.fillna(False))


def v_adx_bell(df, thr=4):
    adx, pdi, mdi = adx_di(df)
    a, p, m = adx.to_numpy(), pdi.to_numpy(), mdi.to_numpy()
    n = len(df)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    armed, low = False, np.nan
    for i in range(1, n):
        if np.isnan(a[i]) or np.isnan(p[i]) or np.isnan(m[i]):
            continue
        if a[i] < p[i] and a[i] < m[i]:
            if not armed or a[i] < low:
                low = a[i]
            armed = True
        if armed and a[i] - low >= thr:
            if p[i] > m[i]:
                long[i] = True
            elif m[i] > p[i]:
                short[i] = True
            armed = False
    return _pack(df, long, short, _arr(m > p), _arr(p > m))


def v_triple_screen(df, second="fi", win=5, screens="all"):
    wk = weekly_hist_slope_daily(df)
    e, _, _ = _ema_state(df, 13)
    if second == "fi":
        fi = force_index2(df)
        s_l, s_s = fi < 0, fi > 0
    elif second == "stoch":
        st = stochastic(df, win, 3)
        s_l, s_s = st < 30, st > 70
    else:
        bear, bull = df["Low"] - e, df["High"] - e
        s_l, s_s = (bear < 0) & (bear > bear.shift(1)), (bull > 0) & (bull < bull.shift(1))
    w_up, w_dn = wk > 0, wk < 0
    if screens == "all":
        long, short = w_up & s_l, w_dn & s_s
    elif screens == "weekly_only":
        long, short = w_up, w_dn
    else:                                   # "no_weekly": daily oscillator alone
        long, short = s_l, s_s
    # trailing buy-stop: previous high + 1 tick (short: previous low - 1 tick)
    tick = 0.05
    return _pack(df, long.fillna(False), short.fillna(False),
                 (wk < 0).fillna(False), (wk > 0).fillna(False),
                 long_lvl=(df["High"] + tick).to_numpy(), short_lvl=(df["Low"] - tick).to_numpy())


def variant_specs(family):
    """-> list of (variant, params_without_atr, fn, mgmt) ; mgmt = dict(be_atr, trail_frac)."""
    S = []
    if family == "ema13":
        for n in (9, 13, 20):
            S.append(("ema_dip", {"n": n}, lambda d, n=n: v_ema13(d, n), {"be": "ema"}))
    elif family == "ema_gate":
        for n in (9, 13, 21, 26):
            S.append(("slope_turn", {"n": n}, lambda d, n=n: v_ema_gate(d, n), {}))
    elif family == "roc":
        for kind in ("roc", "mom"):
            for n in (5, 6, 7):
                S.append((f"{kind}_centerline", {"n": n},
                          lambda d, n=n, k=kind: v_roc(d, n, k), {}))
    elif family == "stoch_filter":
        S.append(("baseline", {"band": 0}, lambda d: v_stoch_filter(d, None), {"be": "ema"}))
        for hi, lo in ((80, 20), (75, 25), (70, 30)):
            S.append(("stoch_veto", {"band": hi}, lambda d, h=hi, l=lo: v_stoch_filter(d, h, l),
                      {"be": "ema"}))
    elif family == "obv":
        for mode in ("confirm", "diverge", "breakout"):
            for lb in (10, 20, 40):
                S.append((mode, {"lb": lb}, lambda d, m=mode, lb=lb: v_obv(d, m, lb), {}))
    elif family == "elder_ray":
        S.append(("plain", {"lb": 0}, lambda d: v_elder_ray(d, "plain"), {}))
        S.append(("veto", {"lb": 0}, lambda d: v_elder_ray(d, "veto"), {}))
        for lb in (3, 5, 10):
            S.append(("exit_div", {"lb": lb}, lambda d, lb=lb: v_elder_ray(d, "exit_div", lb), {}))
    elif family == "adx_bell":
        for thr in (3, 4, 5):
            S.append(("ring_bell", {"pts": thr}, lambda d, t=thr: v_adx_bell(d, t), {}))
    elif family == "triple_screen":
        mg = {"be_atr": 1.0, "trail_frac": 0.5}
        for sec, win in (("fi", 2), ("stoch", 5), ("stoch", 14), ("elder", 13)):
            for scr in ("all", "weekly_only", "no_weekly"):
                if sec != "fi" and scr == "weekly_only":
                    continue                          # identical to fi's weekly_only
                S.append((f"{sec}_{scr}", {"w": win},
                          lambda d, s=sec, w=win, sc=scr: v_triple_screen(d, s, w, sc), mg))
    else:
        raise ValueError(family)
    return S


# ---------------------------------------------------------------- simulator

def simulate(df, sig, direction, atr_mult, mgmt=None, atr_n=14, max_hold=MAX_HOLD_BARS,
             cost=COST_ROUND_TRIP):
    """Return list of trades dict(ret, hold, reason). Stop on every trade."""
    mgmt = mgmt or {}
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    a = atr(df, atr_n).to_numpy()
    entry = sig[direction]
    lvl = sig[direction + "_lvl"]
    exitf = sig["exit_" + direction]
    tgt_arr = sig.get(direction + "_tgt")      # optional per-entry target price (B-623)
    sr_arr = sig.get(direction + "_sr")        # optional per-entry S/R level (B-607)
    ema13 = ema(df["Close"], 13).to_numpy()
    n = len(df)
    trades, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        lv = lvl[s]
        if np.isnan(lv):
            px = o[e]
        elif d == 1:
            if h[e] < lv:
                continue
            px = max(o[e], lv)
        else:
            if l[e] > lv:
                continue
            px = min(o[e], lv)
        if px <= 0:
            continue
        risk = atr_mult * a[s]
        stop = px - d * risk
        extreme, be_done = px, False
        tgt = None if tgt_arr is None or np.isnan(tgt_arr[s]) or d * (tgt_arr[s] - px) <= 0 else tgt_arr[s]
        sr = None if sr_arr is None or np.isnan(sr_arr[s]) else sr_arr[s]
        exit_px, reason, j = None, None, e
        for j in range(e, min(n, e + max_hold + 1)):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                gap = o[j] if j > e else None
                exit_px = (min(gap, stop) if d == 1 else max(gap, stop)) if gap is not None else stop
                reason = "breakeven_stop" if be_done and abs(stop - px) < 1e-9 else (
                    "trail_stop" if be_done else "stop_loss")
                break
            if tgt is not None and ((d == 1 and h[j] >= tgt) or (d == -1 and l[j] <= tgt)):
                gap = o[j] if j > e else None
                exit_px = (max(gap, tgt) if d == 1 else min(gap, tgt)) if gap is not None else tgt
                reason = "target_hit"
                break
            extreme = max(extreme, h[j]) if d == 1 else min(extreme, l[j])
            sr_atr = mgmt.get("sr_atr")
            if sr is not None and sr_atr is not None and d * (extreme - (sr - d * sr_atr * a[s])) >= 0:
                # price reached the S/R zone: tighten the protective stop to a trail off the extreme
                tight = extreme - d * mgmt.get("sr_trail_atr", 1.0) * a[s]
                stop = max(stop, tight) if d == 1 else min(stop, tight)
            be_atr = mgmt.get("be_atr")
            if be_atr is not None and d * (extreme - px) >= be_atr * a[s]:
                be_done = True
            if mgmt.get("be") == "ema" and not be_done and d * (c[j] - ema13[j]) > 0 and j > e:
                be_done = True
            if be_done:
                new = px
                if mgmt.get("trail_frac"):
                    new = px + d * mgmt["trail_frac"] * d * (extreme - px)
                stop = max(stop, new) if d == 1 else min(stop, new)
            if exitf[j] and j > e:
                exit_px, reason = c[j], "rule_exit"
                break
            if j == e + max_hold:
                exit_px, reason = c[j], "max_hold_timeout"
                break
        if exit_px is None:
            exit_px, reason, j = c[n - 1], "data_end", n - 1
        ret = d * (exit_px - px) / px - cost
        trades.append({"ret": float(ret), "hold": int(j - e + 1), "reason": reason, "s": int(s)})
        free = j
    return trades


# ---------------------------------------------------------------- aggregation

def new_agg():
    return {"n": 0, "wins": 0, "win_sum": 0.0, "loss_sum": 0.0, "gwin_sum": 0.0, "gloss_sum": 0.0,
            "hold_sum": 0, "reasons": {}}


def add_trades(agg, trades, cost=COST_ROUND_TRIP):
    for t in trades:
        r = t["ret"]
        agg["n"] += 1
        agg["hold_sum"] += t["hold"]
        agg["reasons"][t["reason"]] = agg["reasons"].get(t["reason"], 0) + 1
        if r > 0:
            agg["wins"] += 1
            agg["win_sum"] += r
        else:
            agg["loss_sum"] += -r
        g = r + cost
        if g > 0:
            agg["gwin_sum"] += g
        else:
            agg["gloss_sum"] += -g


def merge_aggs(a, b):
    for k in ("n", "wins", "win_sum", "loss_sum", "gwin_sum", "gloss_sum", "hold_sum"):
        a[k] += b[k]
    for r, v in b["reasons"].items():
        a["reasons"][r] = a["reasons"].get(r, 0) + v
    return a


def summarize(agg):
    n = agg["n"]
    pf = (agg["win_sum"] / agg["loss_sum"]) if agg["loss_sum"] > 0 else (float("inf") if n else 0.0)
    gpf = (agg["gwin_sum"] / agg["gloss_sum"]) if agg["gloss_sum"] > 0 else (float("inf") if n else 0.0)
    return {"n": n, "pfnet": round(pf, 3) if pf != float("inf") else None,
            "pf_gross": round(gpf, 3) if gpf != float("inf") else None,
            "win_pct": round(100.0 * agg["wins"] / n, 2) if n else 0.0,
            "avg_hold_bars": round(agg["hold_sum"] / n, 2) if n else 0.0,
            "avg_net_ret_pct": round(100.0 * (agg["win_sum"] - agg["loss_sum"]) / n, 3) if n else 0.0,
            "exit_reasons": dict(sorted(agg["reasons"].items()))}


# ---------------------------------------------------------------- driver

def run_symbol(df, family, tf, aggs):
    for variant, params, fn, mgmt in variant_specs(family):
        try:
            sig = fn(df)
        except Exception as ex:                       # one bad variant must not kill a shard
            print("VARIANT ERROR", family, variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in ATR_MULTS:
                tag = make_tag(family, variant, direction, tf, {**params, "atr": am})
                add_trades(aggs.setdefault(tag, new_agg()),
                           simulate(df, sig, direction, am, mgmt))


def prep(raw):
    df = raw.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    df = df.sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna()


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
            df = prep(raw)
            fetched += 1
            run_symbol(df, args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched,
               "universe": len(syms), "aggs": aggs},
              open(os.path.join(args.out, f"{args.family}_{args.shard}.json"), "w"))


def merge_dir(path):
    merged, fetched = {}, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        for tag, ag in d["aggs"].items():
            merge_aggs(merged.setdefault(tag, new_agg()), ag)
    rows = [{"tag": t, **summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "cost_round_trip": COST_ROUND_TRIP, "rows": rows}


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
        res = merge_dir(args.merge)
        print(f"symbols fetched (sum over families): {res['symbols_fetched']}")
        print(f"{'tag':90s} {'n':>7s} {'PFnet':>7s} {'win%':>6s} {'hold':>5s}  exits")
        for r in res["rows"]:
            print(f"{r['tag']:90s} {r['n']:7d} {str(r['pfnet']):>7s} {r['win_pct']:6.1f} "
                  f"{r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
