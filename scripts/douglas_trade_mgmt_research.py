#!/usr/bin/env python3
"""Douglas / Elder trade-management research (backlog B-501, B-531, B-532, B-533, B-534, B-535,
B-537, B-545, B-546, B-551, B-552, B-553, B-554, B-561, B-572, B-574, B-605, B-566).
Research only: no live wiring, no main.py edits.

One R-aware simulator (stop on EVERY trade, ATR multiple sweep 1.5/2/3, 0.8% round trip,
next-bar-open entry, BOTH directions via the reciprocal-price mirror, daily bars by default,
full universe via main._load_nse_universe_from_file()). The SAME two base entry sets (EMA13
dip-buy, 20-bar close breakout) are replayed under different trade-management overlays so the
management effect is isolated. B-529 (structural stop) and B-538 (exhaustion exit) are already
covered by scripts/exit_family_research.py and are not repeated here.

Families (one workflow job each):
  exits  B-566 baseline (stop never widened) | B-531 breakeven ratchet at 0.5/1/1.5/2R (+5% R
         offset) | B-532/B-605 scale-out thirds at 1R and 2R, BE after 2nd third, runner on ATR
         trail | B-535 runner on a structure trail (5-bar low/high) with buffer 0/0.1/0.25 ATR
         | B-533 min reward:risk room filter 1/1.5/2/2.5/3/4 (room to the 60-bar extreme)
         | B-537 time stop 3/5/10/20/30 bars | B-501 O'Neil pyramid add (0.5 unit at +2.5%, stop
         to first entry) | B-534/B-574 every trade records MFE/MAE in R: share of LOSERS that first
         reached >=0.5R / >=1R is reported per tag
  entry  B-545 chase cap 0.1/0.25/0.5/1.0 ATR | B-546 cooldown after a stop-out 0/3/6/12 bars
         | B-561/B-572 limit entry at signal close -0.25 ATR, cancel after 1/3/5 bars (fill model)
         | B-551 weekly-trend gate | B-552 momentum-as-conviction sign(c - c[N]) N 10/20/50
         | B-553 bar-pressure (signed volume sum N 10/20) | B-554 ADX regime gate 20/25

Usage:
  python3 scripts/douglas_trade_mgmt_research.py --family exits --shard 0 --nshards 4 --out out/
  python3 scripts/douglas_trade_mgmt_research.py --merge out/ --json merged.json
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
from elder_patterns_research import both, _exit_ema  # noqa: E402
from elder_trend_context_research import weekly_up  # noqa: E402

FAMILIES = ("exits", "entry")
TAGFAM = {"exits": "trademgmt_exit", "entry": "trademgmt_entry"}
EXTRA = ("losers", "losers_mfe_half", "losers_mfe_1r", "mfe_r_sum", "mae_r_sum")


# ------------------------------------------------------------------ base entries
def b_dip(df):
    return er.v_ema13(df, 13)


def _brk_det(df):
    c, h = df["Close"], df["High"]
    return c > h.shift(1).rolling(20).max(), _exit_ema(df)


b_brk = both(_brk_det)
BASES = {"dip": b_dip, "brk20": b_brk}


def gate(sig, df, gl, gs):
    n = len(df)
    sig = dict(sig)
    sig["long"] = sig["long"] & np.asarray(pd.Series(gl).reindex(df.index).fillna(False), bool)
    sig["short"] = sig["short"] & np.asarray(pd.Series(gs).reindex(df.index).fillna(False), bool)
    return sig


# ------------------------------------------------------------------ simulator
def sim_r(df, sig, direction, am, opt, max_hold=er.MAX_HOLD_BARS, cost=er.COST_ROUND_TRIP):
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    entry, exitf = sig[direction], sig["exit_" + direction]
    n = len(df)
    roll = (pd.Series(h).shift(1).rolling(60).max().to_numpy() if d == 1
            else pd.Series(l).shift(1).rolling(60).min().to_numpy())
    mh = opt.get("max_hold", max_hold)
    trades, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px, start = o[e], e
        if opt.get("limit"):
            lim = c[s] - d * 0.25 * a[s]
            fill = None
            for j in range(e, min(n, e + opt["limit"])):
                if (d == 1 and l[j] <= lim) or (d == -1 and h[j] >= lim):
                    fill = j
                    px = min(o[j], lim) if d == 1 else max(o[j], lim)
                    break
            if fill is None:
                continue
            start = fill
        elif opt.get("chase") is not None and abs(px - c[s]) > opt["chase"] * a[s]:
            continue
        if px <= 0:
            continue
        stop = px - d * am * a[s]
        risk = d * (px - stop)
        if opt.get("min_rr"):
            room = d * (roll[s] - px) if not np.isnan(roll[s]) else -1
            if room < opt["min_rr"] * risk:
                continue
        w_open, pnl, w_inv = 1.0, 0.0, 1.0
        extreme = adverse = px
        mfe = mae = 0.0
        t1 = t2 = be = added = False
        reason, exit_j, j = None, start, start
        scale = opt.get("scale")
        for j in range(start, min(n, start + mh + 1)):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                gap = o[j] if j > start else None
                fp = stop if gap is None else (min(gap, stop) if d == 1 else max(gap, stop))
                pnl += w_open * d * (fp - px) / px
                reason = "stop_loss" if (not be and not t2) else "protected_stop"
                w_open = 0.0
                break
            extreme = max(extreme, h[j]) if d == 1 else min(extreme, l[j])
            adverse = min(adverse, l[j]) if d == 1 else max(adverse, h[j])
            mfe = max(mfe, d * (extreme - px) / risk)
            mae = max(mae, d * (px - adverse) / risk)
            if opt.get("pyramid") and not added and d * (extreme - px) / px >= opt["pyramid"]:
                added = True
                px2 = px * (1 + d * opt["pyramid"])
                pnl_add_entry = px2
                stop = px if d == 1 and px > stop else (px if d == -1 and px < stop else stop)
                w_inv = 1.5
            if scale:
                if not t1 and mfe >= 1.0:
                    pnl += (1 / 3) * d * (risk * 1.0) / px
                    w_open -= 1 / 3
                    t1 = True
                if t1 and not t2 and mfe >= 2.0:
                    pnl += (1 / 3) * d * (risk * 2.0) / px
                    w_open -= 1 / 3
                    t2 = True
                    stop = max(stop, px) if d == 1 else min(stop, px)
                if t2:
                    if scale == "struct":
                        k = 5
                        lo = l[max(0, j - k + 1):j + 1].min() if d == 1 else h[max(0, j - k + 1):j + 1].max()
                        ns = lo - d * opt.get("buf", 0.0) * a[s]
                    else:
                        ns = extreme - d * am * a[s]
                    stop = max(stop, ns) if d == 1 else min(stop, ns)
            if opt.get("be_r") is not None and not be and mfe >= opt["be_r"]:
                be = True
                ns = px + d * 0.05 * risk
                stop = max(stop, ns) if d == 1 else min(stop, ns)
            if not scale and exitf[j] and j > start and not opt.get("no_rule_exit"):
                pnl += w_open * d * (c[j] - px) / px
                reason, w_open = "rule_exit", 0.0
                break
            if scale and t2 and exitf[j] and j > start:
                pnl += w_open * d * (c[j] - px) / px
                reason, w_open = "rule_exit", 0.0
                break
            if j == start + mh:
                pnl += w_open * d * (c[j] - px) / px
                reason, w_open = "max_hold_timeout", 0.0
                break
        if w_open > 0:
            pnl += w_open * d * (c[min(j, n - 1)] - px) / px
            reason = reason or "data_end"
        if added:
            pnl += 0.5 * d * (c[j] - pnl_add_entry) / pnl_add_entry if reason in ("rule_exit", "max_hold_timeout", "data_end") \
                else 0.5 * d * (stop - pnl_add_entry) / pnl_add_entry
        ret = pnl / w_inv - cost
        trades.append({"ret": float(ret), "hold": int(j - start + 1), "reason": reason, "mfe": mfe, "mae": mae, "i0": int(start), "i1": int(j)})
        free = j + (opt.get("cooldown", 0) if reason == "stop_loss" else 0)
    return trades


# ------------------------------------------------------------------ aggregation (extras)
def new_agg():
    g = er.new_agg()
    g.update({k: 0.0 for k in EXTRA})
    return g


def add_trades(agg, trades):
    er.add_trades(agg, trades)
    for t in trades:
        agg["mfe_r_sum"] += t["mfe"]
        agg["mae_r_sum"] += t["mae"]
        if t["ret"] <= 0:
            agg["losers"] += 1
            agg["losers_mfe_half"] += t["mfe"] >= 0.5
            agg["losers_mfe_1r"] += t["mfe"] >= 1.0


def merge_aggs(a, b):
    er.merge_aggs(a, b)
    for k in EXTRA:
        a[k] = a.get(k, 0.0) + b.get(k, 0.0)
    return a


def summarize(agg):
    r = er.summarize(agg)
    n, L = agg["n"], agg.get("losers", 0)
    r["avg_mfe_r"] = round(agg.get("mfe_r_sum", 0) / n, 3) if n else 0.0
    r["avg_mae_r"] = round(agg.get("mae_r_sum", 0) / n, 3) if n else 0.0
    r["losers_reached_half_r_pct"] = round(100 * agg.get("losers_mfe_half", 0) / L, 2) if L else 0.0
    r["losers_reached_1r_pct"] = round(100 * agg.get("losers_mfe_1r", 0) / L, 2) if L else 0.0
    return r


# ------------------------------------------------------------------ variants
def variant_specs(family):
    """-> list of (variant, params, make_sig(df, base_fn), opt)"""
    S = []

    def plain(df, bf):
        return bf(df)

    def add(name, params, opt, mk=plain):
        for bname, bf in BASES.items():
            S.append((f"{bname}_{name}", dict(params), (lambda d, bf=bf, mk=mk: mk(d, bf)), opt))

    if family == "exits":
        add("baseline", {"x": 0}, {})
        for r in (0.5, 1.0, 1.5, 2.0):
            add("be_ratchet", {"r": r}, {"be_r": r})
        add("scale_atr", {"x": 0}, {"scale": "atr"})
        for buf in (0.0, 0.1, 0.25):
            add("scale_struct", {"buf": buf}, {"scale": "struct", "buf": buf})
        for rr in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
            add("min_rr", {"rr": rr}, {"min_rr": rr})
        for hb in (3, 5, 10, 20, 30):
            add("time_stop", {"h": hb}, {"max_hold": hb})
        add("pyramid", {"add": 0.025}, {"pyramid": 0.025})
    elif family == "entry":
        for k in (0.1, 0.25, 0.5, 1.0):
            add("chase_cap", {"k": k}, {"chase": k})
        for nb in (0, 3, 6, 12):
            add("cooldown", {"cd": nb}, {"cooldown": nb})
        for nb in (1, 3, 5):
            add("limit_entry", {"nb": nb}, {"limit": nb})

        def mk_wk(df, bf):
            wk = weekly_up(df)
            return gate(bf(df), df, wk, ~wk)
        add("wk_gate", {"wk": 13}, {}, mk_wk)
        for N in (10, 20, 50):
            def mk_mom(df, bf, N=N):
                s = np.sign(df["Close"] - df["Close"].shift(N))
                return gate(bf(df), df, s > 0, s < 0)
            add("mom_conv", {"n": N}, {}, mk_mom)
        for N in (10, 20):
            def mk_bp(df, bf, N=N):
                p = (np.sign(df["Close"] - df["Open"]) * df["Volume"]).rolling(N).sum()
                return gate(bf(df), df, p > 0, p < 0)
            add("bar_pressure", {"n": N}, {}, mk_bp)
        for thr in (20, 25):
            def mk_adx(df, bf, thr=thr):
                adx, _, _ = er.adx_di(df)
                t = adx > thr
                return gate(bf(df), df, t, t)
            add("adx_gate", {"thr": thr}, {}, mk_adx)
    else:
        raise ValueError(family)
    return S


def run_symbol(df, family, tf, aggs):
    for variant, params, mk, opt in variant_specs(family):
        try:
            sig = mk(df)
        except Exception as ex:
            print("VARIANT ERROR", family, variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag(TAGFAM[family], variant, direction, tf, {**params, "atr": am})
                trades = sim_r(df, sig, direction, am, opt)
                if trades:
                    add_trades(aggs.setdefault(tag, new_agg()), trades)


def merge_dir(path):
    import glob
    merged, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        d = json.load(open(f))
        if "aggs" not in d:
            continue
        fetched += d.get("fetched", 0)
        universe += d.get("universe", 0)
        for tag, ag in d["aggs"].items():
            merge_aggs(merged.setdefault(tag, new_agg()), ag)
    rows = [{"tag": t, **summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    return {"symbols_fetched": fetched, "universe_size": universe, "cost_round_trip": er.COST_ROUND_TRIP, "rows": rows}


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
        res = merge_dir(args.merge)
        print(f"universe symbols: {res['universe_size']}  fetched with data: {res['symbols_fetched']}  "
              f"round-trip cost: {res['cost_round_trip']}")
        print(f"{'tag':96s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s} {'MFEr':>5s} {'L>=.5R%':>7s} {'L>=1R%':>7s}  exits")
        for r in res["rows"]:
            print(f"{r['tag']:96s} {r['n']:7d} {str(r['pfnet']):>7s} {str(r['pf_gross']):>8s} {r['win_pct']:6.1f} "
                  f"{r['avg_hold_bars']:5.1f} {r['avg_mfe_r']:5.2f} {r['losers_reached_half_r_pct']:7.1f} "
                  f"{r['losers_reached_1r_pct']:7.1f}  {r['exit_reasons']}")
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
