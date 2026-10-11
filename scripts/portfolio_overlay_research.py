#!/usr/bin/env python3
"""Portfolio / sizing / index-regime / statistical-gate research (backlog B-501 context,
B-504, B-507, B-508, B-509, B-516, B-517, B-518, B-519, B-527, B-528, B-539, B-540, B-541,
B-543, B-544, B-548, B-549, B-555, B-556, B-557, B-564, B-565, B-569 cost sweep 0.4/0.8/1.2%, B-604). Research only.

Two stages.
  collect  (sharded, one matrix job per shard): runs two base entry sets (EMA13 dip-buy, 20-bar
           breakout; BOTH directions via the reciprocal-price mirror; ATR stop 1.5/2/3; stop on
           every trade; 0.8% round trip; full universe via main._load_nse_universe_from_file())
           and stores every trade compactly (entry/exit time, net return, stop distance as a
           fraction of price, hold, entry price, 20-bar traded value, exit reason).
  merge    (one job): rebuilds each base stream chronologically and applies overlays:
    portfolio sizing sim   concurrency cap K=10 open positions, equity compounding on REALIZED
                           equity, size = min(risk_pct / stop_frac, notional cap) x policy mult
        B-527/B-564  fixed-fractional risk 0.25/0.5/1/2% (2% = Elder's rule)
        B-518        notional cap per stock 5/10/20% of equity at 2% risk
        B-565        pass-the-trade: skip if stop distance > 4/6/8% of price
        B-543        euphoria (size x1.25 per win streak, max 4) vs capped
        B-544/B-517  loss-streak breaker: size x0.5 after K=2..5 straight losses
        B-549        drawdown size ladder (-5% x0.5, -10% x0.25) and equity<MA20(equity) filter
        B-555        capital ramp in 20-trade blocks (0.5 -> 2% by profitable blocks)
        B-604        index-regime sizing (x1 with the 200DMA regime, x0.5 against it)
        B-541        rolling 20-trade paper-expectancy monitor: pause when last-20 expectancy < 0
    statistics             B-539 expectancy, B-540 bootstrap 95% CI on PFnet, B-504 O'Neil
                           acceptance (avg win/avg loss >= 2, win >= 33%), B-548 lag-1..3
                           autocorrelation + runs test, B-528 worst losing run vs risk,
                           B-556 bootstrap p95 drawdown vs risk_pct, B-557 walk-forward
                           (first 60% vs last 40% and per-year), B-516 PFnet by entry month,
                           B-519 PFnet by entry price and traded-value bucket
    index regime gates     B-507/B-508/B-509 on ^NSEI: 200DMA, follow-through-day/distribution-
                           day state machine, distribution-only; longs need bull, shorts need
                           not-bull (shown with and without the gate)
Approximations (stated, not hidden): each stream is a mechanical entry set, trades never reduce
one another except through the K cap; no intraday path inside a bar; index volume may be zero
on old Yahoo data (FTD then falls back to the 200DMA state).

Usage:
  python3 scripts/portfolio_overlay_research.py collect --shard 0 --nshards 8 --out out/
  python3 scripts/portfolio_overlay_research.py merge --dir out/ --json merged.json
"""
from __future__ import annotations

import argparse
import glob
import heapq
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import douglas_trade_mgmt_research as dm  # noqa: E402

COST = er.COST_ROUND_TRIP
TF = "1d"


# ------------------------------------------------------------------ collect stage
def collect_symbol(df, streams):
    tv = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
    a = er.atr(df).to_numpy()
    cl = df["Close"].to_numpy()
    secs = (df.index.asi8 // 10 ** 9).astype(np.int64)
    for bname, bf in dm.BASES.items():
        try:
            sig = bf(df)
        except Exception as ex:
            print("BASE ERROR", bname, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                key = f"{bname}|{direction}|{am}"
                for t in dm.sim_r(df, sig, direction, am, {}):
                    i0, i1 = t["i0"], t["i1"]
                    s = max(i0 - 1, 0)
                    streams.setdefault(key, []).append([
                        int(secs[i0]), int(secs[i1]), round(t["ret"], 5),
                        round(float(am * a[s] / cl[s]), 5) if cl[s] > 0 else 0.0, t["hold"],
                        round(float(cl[i0]), 2), round(float(tv[s]) if not np.isnan(tv[s]) else 0.0, 0),
                        t["reason"]])


def _collect_main(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    streams, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            fetched += 1
            collect_symbol(er.prep(raw), streams)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"collect shard {args.shard}: fetched {fetched}/{len(syms)}, streams {len(streams)}, "
          f"trades {sum(len(v) for v in streams.values())}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"fetched": fetched, "universe": len(syms), "streams": streams},
              open(os.path.join(args.out, f"collect_{args.shard}.json"), "w"))


# ------------------------------------------------------------------ statistics
def stats(tr):
    """tr: list of trade lists. -> dict with PFnet, gross, win %, hold, expectancy, O'Neil ratio."""
    if not tr:
        return {"n": 0, "pfnet": None, "pf_gross": None, "win_pct": 0.0, "avg_hold_bars": 0.0}
    r = np.array([t[2] for t in tr], float)
    hold = np.array([t[4] for t in tr], float)
    w, lo = r[r > 0], -r[r <= 0]
    g = r + COST
    gw, gl = g[g > 0].sum(), -g[g <= 0].sum()
    reasons = {}
    for t in tr:
        reasons[t[7]] = reasons.get(t[7], 0) + 1
    awin = float(w.mean()) if len(w) else 0.0
    aloss = float(lo.mean()) if len(lo) else 0.0
    return {"n": int(len(r)), "pfnet": round(w.sum() / lo.sum(), 3) if lo.sum() > 0 else None,
            "pf_gross": round(gw / gl, 3) if gl > 0 else None,
            "win_pct": round(100 * len(w) / len(r), 2), "avg_hold_bars": round(float(hold.mean()), 2),
            "expectancy_pct": round(100 * float(r.mean()), 3),
            "avg_win_pct": round(100 * awin, 3), "avg_loss_pct": round(100 * aloss, 3),
            "win_loss_ratio": round(awin / aloss, 3) if aloss > 0 else None,
            "oneil_ok": bool(aloss > 0 and awin / aloss >= 2 and len(w) / len(r) >= 0.33),
            "exit_reasons": dict(sorted(reasons.items()))}


def pf_of(r):
    r = np.asarray(r, float)
    lo = -r[r <= 0].sum()
    return r[r > 0].sum() / lo if lo > 0 else np.nan


def boot_ci(r, iters=300, seed=7):
    r = np.asarray(r, float)
    if len(r) < 30:
        return None, None
    rng = np.random.default_rng(seed)
    v = [pf_of(r[rng.integers(0, len(r), len(r))]) for _ in range(iters)]
    v = np.array([x for x in v if not np.isnan(x)])
    return (round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)) if len(v) else (None, None)


def independence(r, lags=(1, 2, 3)):
    r = np.asarray(r, float)
    if len(r) < 50:
        return {}
    out = {}
    x = r - r.mean()
    den = (x * x).sum()
    for L in lags:
        out[f"ac{L}"] = round(float((x[L:] * x[:-L]).sum() / den), 4) if den > 0 else None
    s = r > 0
    n1, n2 = int(s.sum()), int((~s).sum())
    runs = 1 + int((s[1:] != s[:-1]).sum())
    if n1 and n2:
        mu = 2 * n1 * n2 / (n1 + n2) + 1
        var = 2 * n1 * n2 * (2 * n1 * n2 - n1 - n2) / (((n1 + n2) ** 2) * (n1 + n2 - 1))
        out["runs_z"] = round((runs - mu) / var ** 0.5, 3) if var > 0 else None
    best = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        best = max(best, cur)
    out["max_losing_run"] = best
    return out


# ------------------------------------------------------------------ portfolio sim
def simulate_portfolio(trades, K=10, risk=0.01, cap=0.10, policy=None, regime=None):
    """trades sorted by entry time. Returns dict(final_mult, max_dd_pct, taken(list of trades))."""
    policy = policy or {}
    eq, peak, maxdd = 1.0, 1.0, 0.0
    heap, openp, taken = [], 0, []
    closed, paper, eqhist = [], [], [1.0]
    sw = sl = 0
    block_lvl, block_start_eq, block_n = 0, 1.0, 0
    ramp = (0.005, 0.01, 0.015, 0.02)
    seq = 0

    def settle(tnow):
        nonlocal eq, peak, maxdd, openp, sw, sl, block_lvl, block_start_eq, block_n
        while heap and heap[0][0] <= tnow:
            _, _, pnl, ret, was_taken = heapq.heappop(heap)
            paper.append(ret)
            if was_taken:
                openp -= 1
                eq += pnl
                eqhist.append(eq)
                closed.append(ret)
                sw, sl = (sw + 1, 0) if ret > 0 else (0, sl + 1)
                peak = max(peak, eq)
                maxdd = max(maxdd, 1 - eq / peak)
                block_n += 1
                if block_n >= 20:
                    block_lvl = min(block_lvl + 1, 3) if eq > block_start_eq else max(block_lvl - 1, 0)
                    block_start_eq, block_n = eq, 0

    for t in trades:
        settle(t[0])
        rf = t[3] if t[3] > 0 else 0.05
        take = openp < K
        if take and policy.get("skip_rf") and rf > policy["skip_rf"]:
            take = False
        if take and policy.get("monitor20") and len(paper) >= 20 and np.mean(paper[-20:]) < 0:
            take = False
        mult = 1.0
        if policy.get("euphoria"):
            mult = 1.25 ** min(sw, 4)
        if policy.get("loss_k") and sl >= policy["loss_k"]:
            mult *= 0.5
        if policy.get("ddladder"):
            dd = 1 - eq / peak
            mult *= 0.25 if dd >= 0.10 else 0.5 if dd >= 0.05 else 1.0
        if policy.get("eqfilter") and len(eqhist) >= 20 and eq < np.mean(eqhist[-20:]):
            mult *= 0.5
        r_use = ramp[block_lvl] if policy.get("ramp") else risk
        if policy.get("regime") is not None and regime is not None:
            ok = regime(t[0])
            mult *= 1.0 if ok else 0.5
        size = min(r_use / rf, cap) * mult * eq
        pnl = size * t[2]
        seq += 1
        heapq.heappush(heap, (t[1], seq, pnl if take else 0.0, t[2], take))
        if take:
            openp += 1
            taken.append(t)
    settle(float("inf"))
    return {"final_mult": round(eq, 3), "max_dd_pct": round(100 * maxdd, 2), "taken": taken}


POLICIES = (
    [(f"rp{p}", {"risk": p / 100}) for p in (0.25, 0.5, 1.0, 2.0)]
    + [(f"cap{c}", {"risk": 0.02, "cap": c / 100}) for c in (5, 10, 20)]
    + [(f"passtrade{p}", {"risk": 0.02, "policy": {"skip_rf": p / 100}}) for p in (4, 6, 8)]
    + [("euphoria_up", {"risk": 0.01, "policy": {"euphoria": 1}}), ("euphoria_capped", {"risk": 0.01})]
    + [(f"lossstreak{k}", {"risk": 0.01, "policy": {"loss_k": k}}) for k in (2, 3, 4, 5)]
    + [("ddladder", {"risk": 0.01, "policy": {"ddladder": 1}}), ("eqfilter", {"risk": 0.01, "policy": {"eqfilter": 1}}),
       ("ramp20", {"risk": 0.01, "policy": {"ramp": 1}}), ("monitor20", {"risk": 0.01, "policy": {"monitor20": 1}}),
       ("idxregime_size", {"risk": 0.01, "policy": {"regime": 1}})]
)


# ------------------------------------------------------------------ index regimes
def index_regimes(idx):
    """idx: DataFrame Close/Volume. Returns dict name -> pd.Series(bool bull) indexed by date."""
    c = idx["Close"]
    v = idx["Volume"] if "Volume" in idx else pd.Series(0.0, index=idx.index)
    dma = c.rolling(200).mean()
    out = {"dma200": (c > dma).fillna(False)}
    chg = c.pct_change()
    dist = ((chg <= -0.002) & (v > v.shift(1))).astype(int)
    dcount = dist.rolling(25).sum().fillna(0)
    vol_ok = v.sum() > 0
    low20 = c.rolling(20).min()
    state = np.zeros(len(c), bool)
    attempt, st = None, False
    cv, vv, ch = c.to_numpy(), v.to_numpy(), chg.to_numpy()
    for i in range(len(c)):
        if i >= 20 and cv[i - 1] <= low20.iloc[i - 1] * 1.0001:
            attempt = i                                   # rally attempt starts after a 20d-low close
        if attempt is not None and 4 <= i - attempt <= 10 and ch[i] >= 0.01 and (vv[i] > vv[i - 1] or not vol_ok):
            st, attempt = True, None
        if st and (dcount.iloc[i] >= 5 or (not np.isnan(dma.iloc[i]) and cv[i] < dma.iloc[i])):
            st = False
        state[i] = st
    out["ftd_dd"] = pd.Series(state, index=c.index)
    out["dd_lt5"] = (dcount < 5)
    return out


def make_regime_fn(series):
    days = {d.date().toordinal(): bool(b) for d, b in series.items()}
    keys = np.array(sorted(days))

    def f(sec):
        o = pd.Timestamp(sec, unit="s").date().toordinal()
        i = np.searchsorted(keys, o, side="right") - 1
        return days[int(keys[i])] if i >= 0 else False
    return f


# ------------------------------------------------------------------ merge stage
def merge(path, json_out=None, idx_df=None):
    streams, fetched, universe = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "collect_*.json"), recursive=True)):
        d = json.load(open(f))
        fetched += d["fetched"]
        universe += d["universe"]
        for k, v in d["streams"].items():
            streams.setdefault(k, []).extend(v)
    regimes = index_regimes(idx_df) if idx_df is not None and len(idx_df) > 300 else {}
    rows = []

    def add(base, direction, am, overlay, params, st, extra=None):
        tag = er.make_tag("pfovl", f"{base}_{overlay}", direction, TF, {**params, "atr": float(am)})
        rows.append({"tag": tag, **st, **(extra or {}), "universe": universe})

    for key, tr in sorted(streams.items()):
        base, direction, am = key.split("|")
        am = float(am)
        tr.sort(key=lambda t: (t[0], t[1]))
        r = [t[2] for t in tr]
        st = stats(tr)
        lo, hi = boot_ci(r)
        add(base, direction, am, "base", {"x": 0}, st,
            {"pfnet_ci95_lo": lo, "pfnet_ci95_hi": hi, **independence(r),
             **{f"pfnet_at_cost_{c}pct": (round(float(pf_of(np.asarray(r) + COST - c / 100)), 3)) for c in (0.4, 0.8, 1.2)}})
        n = len(tr)
        cut = int(n * 0.6)
        add(base, direction, am, "walkfwd_train", {"pct": 60}, stats(tr[:cut]))
        add(base, direction, am, "walkfwd_test", {"pct": 40}, stats(tr[cut:]))
        years = sorted({pd.Timestamp(t[0], unit="s").year for t in tr})
        for y in years:
            add(base, direction, am, "year", {"y": y}, stats([t for t in tr if pd.Timestamp(t[0], unit="s").year == y]))
        for mth in range(1, 13):
            add(base, direction, am, "month", {"m": mth}, stats([t for t in tr if pd.Timestamp(t[0], unit="s").month == mth]))
        for lo_p, hi_p in ((0, 20), (20, 50), (50, 100), (100, 500), (500, 1e9)):
            add(base, direction, am, "pricebucket", {"lo": lo_p, "hi": int(min(hi_p, 999999))},
                stats([t for t in tr if lo_p <= t[5] < hi_p]))
        tvs = np.array([t[6] for t in tr])
        if len(tvs):
            qs = np.quantile(tvs, [0, 0.25, 0.5, 0.75, 1.0])
            for qi in range(4):
                add(base, direction, am, "tvquartile", {"q": qi + 1},
                    stats([t for t in tr if qs[qi] <= t[6] <= qs[qi + 1]]), {"tv_lo": float(qs[qi]), "tv_hi": float(qs[qi + 1])})
        for name, series in regimes.items():
            fn = make_regime_fn(series)
            bull = [t for t in tr if fn(t[0])]
            use = bull if direction == "long" else [t for t in tr if not fn(t[0])]
            add(base, direction, am, f"gate_{name}", {"x": 1}, stats(use), {"kept_pct": round(100 * len(use) / max(n, 1), 1)})
        reg_fn = make_regime_fn(regimes["dma200"]) if "dma200" in regimes else None
        base_run = None
        for pname, spec in POLICIES:
            res = simulate_portfolio(tr, K=10, risk=spec.get("risk", 0.01), cap=spec.get("cap", 0.10),
                                     policy=spec.get("policy"), regime=reg_fn if spec.get("policy", {}).get("regime") else None)
            if pname == "rp1.0":
                base_run = res
            add(base, direction, am, pname, {"k": 10}, stats(res["taken"]),
                {"final_mult": res["final_mult"], "max_dd_pct": res["max_dd_pct"]})
        # B-556 bootstrap p95 drawdown per risk level, B-528 worst-run drawdown
        if base_run and len(base_run["taken"]) > 100:
            tk = base_run["taken"]
            ret = np.array([t[2] for t in tk])
            rfs = np.array([t[3] if t[3] > 0 else 0.05 for t in tk])
            rng = np.random.default_rng(11)
            run = out = 0
            for v in ret:
                run = run + 1 if v <= 0 else 0
                out = max(out, run)
            for rp in (0.25, 0.5, 1.0, 2.0):
                f = np.minimum(rp / 100 / rfs, 0.10)
                dds = []
                for _ in range(200):
                    perm = rng.permutation(len(ret))
                    eqc = np.cumprod(1 + f[perm] * ret[perm] / 1.0)
                    pk = np.maximum.accumulate(eqc)
                    dds.append(float((1 - eqc / pk).max()))
                add(base, direction, am, "bootdd", {"rp": rp},
                    stats(tk), {"p95_dd_pct": round(100 * float(np.percentile(dds, 95)), 2),
                                "worst_run_len": out, "worst_run_risk_pct": round(rp * out, 2)})
    res = {"universe_size": universe, "symbols_fetched": fetched, "cost_round_trip": COST,
           "index_regimes": sorted(regimes), "rows": rows}
    print(f"universe symbols: {universe}  fetched with data: {fetched}  index regimes: {sorted(regimes)}  rows: {len(rows)}")
    print(f"{'tag':100s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s} {'mult':>7s} {'maxDD%':>7s}  exits")
    for rw in sorted(rows, key=lambda x: (x["pfnet"] is None, -(x["pfnet"] or 0))):
        print(f"{rw['tag']:100s} {rw['n']:7d} {str(rw['pfnet']):>7s} {str(rw['pf_gross']):>8s} {rw['win_pct']:6.1f} "
              f"{rw['avg_hold_bars']:5.1f} {str(rw.get('final_mult', '')):>7s} {str(rw.get('max_dd_pct', '')):>7s}  "
              f"{rw.get('exit_reasons', '')}")
    if json_out:
        json.dump(res, open(json_out, "w"), indent=1)
    return res


def _merge_main(args):
    sys.path.insert(0, ".")
    idx = None
    try:
        import main as m
        raw = m.fetch_ohlc("^NSEI", "10y", "1d")
        idx = er.prep(raw)
    except Exception as ex:
        print("INDEX FETCH FAILED (regime gates skipped):", ex, file=sys.stderr)
    merge(args.dir, args.json, idx)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--shard", type=int, default=0)
    c.add_argument("--nshards", type=int, default=8)
    c.add_argument("--interval", default="1d")
    c.add_argument("--period", default="5y")
    c.add_argument("--out", default="out")
    m_ = sub.add_parser("merge")
    m_.add_argument("--dir", required=True)
    m_.add_argument("--json")
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        _collect_main(args)
    else:
        _merge_main(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
