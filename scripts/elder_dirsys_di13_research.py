#!/usr/bin/env python3
"""Elder Directional System remainder (backlog B-588). Research only: no live wiring.

What the earlier dirsys run (scripts/elder_macd_dirgap_research.py, family dirsys, 1d only)
did NOT cover, and this script does:
  1. It used er.adx_di(df) with the DEFAULT period 14. Elder / Wilder is 13. Here n=13 is the
     baseline and n=8 / n=21 are swept (wilder smoothing).
  2. Smoothing type was never swept: Wilder (alpha=1/n) vs EMA (span=n, alpha=2/(n+1)).
  3. Only fixed ATR stops were tested. Here every cell also runs with a trailing stop
     (breakeven at +1 ATR, then 50% of the open profit locked): ts0 fixed, ts1 trailing.
  4. Only 1d. --interval accepts 1d, 1h, 15m, 5m, 1m (yfinance: 1m 7d, 5m/15m 60d, 1h 730d)
     and 4h (built from 1h bars with NSE session-anchored bins starting 09:15).
  5. er.simulate has no bad-bar guard (B-864). Here any trade whose entry bar or hold window
     contains a bar whose Open/Close jumps outside [0.5x, 2x] of the prior Close is dropped and
     counted ("bad_dropped" in the JSON).
  6. Out-of-sample half: each trade is also aggregated into a separate "oos" aggregate when it
     enters in the last 30% of the symbol's bars (simple time split, same tag).
Variants (same four as the daily run): cross_adxrise, cross_noadx, cross_dullgate, cross_overheat.
Both directions, ATR 1.5/2/3, stop on every trade, 0.8% round trip cost, 30-bar max hold,
non-overlapping trades per symbol (er.simulate frees the slot at exit). Full universe via
main._load_nse_universe_from_file(). Every (variant,dir,tf,n,sm,ts,atr) cell is its own tag.

Usage:
  python3 scripts/elder_dirsys_di13_research.py --shard 0 --nshards 8 --interval 1d --out out/
  python3 scripts/elder_dirsys_di13_research.py --merge out/ --json merged.json
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

FAMILY = "dirsys13"
INTERVALS = ("1d", "4h", "1h", "15m", "5m", "1m")
FETCH = {"4h": "1h"}                                  # 4h is resampled from 1h
DEFAULT_PERIOD = {"1d": "5y", "4h": "730d", "1h": "730d", "15m": "60d", "5m": "60d", "1m": "7d"}
# (n, smoothing) combos: Elder baseline 13 in both smoothings, plus period sweep with wilder.
DI_SETS = ((13, "wilder"), (13, "ema"), (8, "wilder"), (21, "wilder"))
SM_CODE = {"wilder": 0, "ema": 1}
STOPS = {0: {}, 1: {"be_atr": 1.0, "trail_frac": 0.5}}   # ts0 fixed ATR stop, ts1 trailing
BAD_LO, BAD_HI = 0.5, 2.0
OOS_FRAC = 0.30


def _alpha(n, sm):
    return 1.0 / n if sm == "wilder" else 2.0 / (n + 1)


def adx_di(df, n=13, sm="wilder"):
    """+DI, -DI, ADX with n-period smoothing (Elder uses 13). Same maths as er.adx_di but the
    period and the smoothing type are explicit."""
    a_ = _alpha(n, sm)
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_n = tr.ewm(alpha=a_, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=a_, adjust=False).mean() / atr_n
    mdi = 100 * mdm.ewm(alpha=a_, adjust=False).mean() / atr_n
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a_, adjust=False).mean(), pdi, mdi


def _pack(df, long, short, ex_l, ex_s):
    def f(x):
        return np.asarray(pd.Series(x).fillna(False), dtype=bool)
    return er._pack(df, f(long), f(short), f(ex_l), f(ex_s))


def v_dirsys(df, n=13, sm="wilder", adx_rise=True, dull_gate=False, overheat=False):
    adx, p, m = adx_di(df, n, sm)
    rising = adx > adx.shift(1)
    long = (p > m) & (p.shift(1) <= m.shift(1))
    short = (m > p) & (m.shift(1) <= p.shift(1))
    if adx_rise:
        long, short = long & rising, short & rising
    if dull_gate:
        trending = (adx > pd.concat([p, m], axis=1).min(axis=1)) & rising
        long, short = long & trending, short & trending
    ex_l, ex_s = m > p, p > m
    if overheat:
        oh = (adx > p) & (adx > m) & (adx < adx.shift(1)) & (adx.shift(1) >= adx.shift(2))
        ex_l, ex_s = ex_l | oh, ex_s | oh
    return _pack(df, long, short, ex_l, ex_s)


VARIANTS = (("cross_adxrise", dict(adx_rise=True, dull_gate=False, overheat=False)),
            ("cross_noadx", dict(adx_rise=False, dull_gate=False, overheat=False)),
            ("cross_dullgate", dict(adx_rise=True, dull_gate=True, overheat=False)),
            ("cross_overheat", dict(adx_rise=True, dull_gate=False, overheat=True)))


def variant_cells():
    """-> list of (variant, params_without_atr_and_ts, fn(df)->sig)."""
    out = []
    for name, kw in VARIANTS:
        for n, sm in DI_SETS:
            out.append((name, {"n": n, "sm": SM_CODE[sm]},
                        lambda d, n=n, sm=sm, kw=kw: v_dirsys(d, n, sm, **kw)))
    return out


def all_tags(tf):
    tags = []
    for variant, params, _ in variant_cells():
        for d in ("long", "short"):
            for ts in STOPS:
                for am in er.ATR_MULTS:
                    tags.append(er.make_tag(FAMILY, variant, d, tf, {**params, "ts": ts, "atr": am}))
    return tags


def bad_bar_mask(o, c):
    bad = np.zeros(len(c), dtype=bool)
    if len(c) < 2:
        return bad
    with np.errstate(divide="ignore", invalid="ignore"):
        ro, rc = o[1:] / c[:-1], c[1:] / c[:-1]
    bad[1:] = ~((ro >= BAD_LO) & (ro <= BAD_HI) & (rc >= BAD_LO) & (rc <= BAD_HI))
    return bad


def guard_trades(trades, bad):
    """Drop trades whose entry bar..exit bar window touches a bad bar. -> (kept, n_dropped)."""
    kept, dropped = [], 0
    for t in trades:
        e = t["s"] + 1
        if bad[e:e + t["hold"]].any():
            dropped += 1
        else:
            kept.append(t)
    return kept, dropped


def resample_4h(df):
    """1h bars -> 4h bars anchored at the 09:15 NSE open (bins 09:15-13:15, 13:15-close)."""
    r = df.resample("4h", offset="9h15min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return r.dropna(subset=["Open", "High", "Low", "Close"])


def run_symbol(df, tf, aggs, oos_aggs, counters):
    bad = bad_bar_mask(df["Open"].to_numpy(float), df["Close"].to_numpy(float))
    split = int(len(df) * (1 - OOS_FRAC))
    for variant, params, fn in variant_cells():
        try:
            sig = fn(df)
        except Exception as ex:
            print("VARIANT ERROR", variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for ts, mgmt in STOPS.items():
                for am in er.ATR_MULTS:
                    tag = er.make_tag(FAMILY, variant, direction, tf, {**params, "ts": ts, "atr": am})
                    trades, nd = guard_trades(er.simulate(df, sig, direction, am, mgmt), bad)
                    counters["bad_dropped"] += nd
                    er.add_trades(aggs.setdefault(tag, er.new_agg()), trades)
                    oos = [t for t in trades if t["s"] >= split]
                    if oos:
                        er.add_trades(oos_aggs.setdefault(tag, er.new_agg()), oos)


def _load(m, sym, interval, period):
    raw = m.fetch_ohlc(sym, period, FETCH.get(interval, interval))
    if raw is None or len(raw) < 120:
        return None
    df = er.prep(raw)
    if interval == "4h":
        df = resample_4h(df)
    return df if len(df) >= 120 else None


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, oos_aggs, counters, fetched = {}, {}, {"bad_dropped": 0}, 0
    period = args.period or DEFAULT_PERIOD[args.interval]
    for s in syms:
        try:
            df = _load(m, s, args.interval, period)
            if df is None:
                continue
            fetched += 1
            run_symbol(df, args.interval, aggs, oos_aggs, counters)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{FAMILY} {args.interval} shard {args.shard}: fetched {fetched}/{len(syms)}, "
          f"tags {len(aggs)}, bad-bar trades dropped {counters['bad_dropped']}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": FAMILY, "interval": args.interval, "period": period, "fetched": fetched,
               "universe": len(syms), "bad_dropped": counters["bad_dropped"],
               "aggs": aggs, "aggs_oos": oos_aggs},
              open(os.path.join(args.out, f"{FAMILY}_{args.interval}_{args.shard}.json"), "w"))


def merge_dir(path):
    merged, oos, fetched, dropped = {}, {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        dropped += d.get("bad_dropped", 0)
        for tag, ag in d["aggs"].items():
            er.merge_aggs(merged.setdefault(tag, er.new_agg()), ag)
        for tag, ag in d.get("aggs_oos", {}).items():
            er.merge_aggs(oos.setdefault(tag, er.new_agg()), ag)
    rows = []
    for t, a in merged.items():
        r = {"tag": t, **er.summarize(a)}
        if t in oos:
            o = er.summarize(oos[t])
            r["oos_n"], r["oos_pfnet"], r["oos_win_pct"] = o["n"], o["pfnet"], o["win_pct"]
        rows.append(r)
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "bad_trades_dropped": dropped,
            "cost_round_trip": er.COST_ROUND_TRIP, "oos_fraction": OOS_FRAC, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=8)
    ap.add_argument("--interval", default="1d", choices=INTERVALS)
    ap.add_argument("--period", default="")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        res = merge_dir(args.merge)
        print(f"symbols fetched (sum over shards): {res['symbols_fetched']}; "
              f"bad-bar trades dropped: {res['bad_trades_dropped']}")
        print(f"{'tag':84s} {'n':>7s} {'PFnet':>7s} {'win%':>6s} {'hold':>5s} {'oosN':>6s} {'oosPF':>6s}")
        for r in res["rows"]:
            print(f"{r['tag']:84s} {r['n']:7d} {str(r['pfnet']):>7s} {r['win_pct']:6.1f} "
                  f"{r['avg_hold_bars']:5.1f} {r.get('oos_n', 0):6d} {str(r.get('oos_pfnet')):>6s}")
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
