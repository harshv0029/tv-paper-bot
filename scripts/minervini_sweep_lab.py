"""Minervini full-universe, both-direction, ATR-sweep harness (backlog B-213..B-265 follow-up).

Complements scripts/minervini_lab.py (n200, long only, 1d, net-only). This harness:
  * universe = main._load_nse_universe_from_file() (full NSE; UNI=n200 only for a cheap pilot)
  * signals = the REAL main.minervini_vcp_entry_signal (long) and minervini_vcp_entry_signal_short
  * exit = initial structural stop + ATR trail swept over ATR_MULTS, max-hold MAXH bars
  * emits per tag: pfnet_gross, pfnet_net, win_pct, n, avg_held_bars, exits breakdown, universe size,
    cost model. Tag grammar: minervini_vcp__atrtrail__<dir>__<tf>__atr<m>_h<MAXH>__v1 (decimal point = d).
Env: UNI=full|n200, INTERVAL=1d (default; 1h/15m/5m bar-count constants change meaning, see docs),
     PERIOD=6y, ATR_MULTS=1.5,2,3,4, MAXH=60. Output docs/minervini_sweep_results_<uni>_<tf>.json
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def mult_tag(m):
    return ("%g" % m).replace(".", "d")


def simulate(df, i, direction, entry, stop0, atr, atr_mult, maxh, cost):
    """Enter at next bar open after signal bar i; returns (gross_ret, net_ret, held, reason) or None."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    n = len(c)
    e = i + 1
    if e >= n:
        return None
    ent = o[e]
    if not ent or np.isnan(ent):
        return None
    sgn = 1.0 if direction == "long" else -1.0
    if (direction == "long" and stop0 >= ent) or (direction == "short" and stop0 <= ent):
        return None
    stop = stop0
    ext = c[i]
    last = min(e + maxh, n) - 1
    for j in range(e, last + 1):
        hit = l[j] <= stop if direction == "long" else h[j] >= stop
        if hit:
            px = min(stop, o[j]) if direction == "long" else max(stop, o[j])
            g = sgn * (px / ent - 1)
            return g, g - cost, j - e + 1, "stop_or_trail"
        if direction == "long":
            ext = max(ext, c[j])
            stop = max(stop, ext - atr_mult * atr)
        else:
            ext = min(ext, c[j])
            stop = min(stop, ext + atr_mult * atr)
    g = sgn * (c[last] / ent - 1)
    return g, g - cost, last - e + 1, "max_hold"


def summarize(gross, net, held, reasons, universe_n, cost):
    gross, net = np.asarray(gross, float), np.asarray(net, float)
    if len(net) == 0:
        return None

    def pf(a):
        lo = -a[a < 0].sum()
        return round(float(a[a > 0].sum() / lo), 3) if lo > 0 else None
    exits = {}
    for r in reasons:
        exits[r] = exits.get(r, 0) + 1
    return {"pfnet_gross": pf(gross), "pfnet": pf(net), "win_pct": round(float((net > 0).mean() * 100), 1),
            "n": int(len(net)), "avg_net_pct": round(float(net.mean() * 100), 3),
            "avg_held_bars": round(float(np.mean(held)), 2), "exits": exits,
            "universe_size": int(universe_n), "cost_round_trip": cost}


def collect(df, fn, step=5):
    out, last = [], -10
    for i in range(210, len(df) - 2):
        if i - last < step:
            continue
        try:
            sig = fn(df.iloc[: i + 1], None)
        except Exception:
            sig = None
        if sig:
            out.append((i, sig["entry_price"], sig["stop_loss"], sig["atr_at_entry"]))
            last = i
    return out


def main_run():
    import yfinance as yf
    import main as app
    from scripts.minervini_lab import clean_bars
    uni = os.environ.get("UNI", "full")
    interval = os.environ.get("INTERVAL", "1d")
    period = os.environ.get("PERIOD", "6y" if interval == "1d" else "60d")
    mults = [float(x) for x in os.environ.get("ATR_MULTS", "1.5,2,3,4").split(",")]
    maxh = int(os.environ.get("MAXH", "60"))
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = list(app.SWING_WATCHLIST) if uni == "n200" else list(app._load_nse_universe_from_file())
    syms = [s for s in syms if s not in app.ETF_SYMBOLS]
    acc = {}
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period=period, interval=interval, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) < 300:
                continue
            for direction, fn in (("long", app.minervini_vcp_entry_signal), ("short", app.minervini_vcp_entry_signal_short)):
                for sg in collect(df, fn):
                    for m in mults:
                        r = simulate(df, sg[0], direction, sg[1], sg[2], sg[3], m, maxh, cost)
                        if r:
                            a = acc.setdefault((direction, m), ([], [], [], []))
                            for k in range(4):
                                a[k].append(r[k])
        print("done", b0, flush=True)
    res = {}
    for (direction, m), (g, nt, hd, rs) in acc.items():
        tag = f"minervini_vcp__atrtrail__{direction}__{interval}__atr{mult_tag(m)}_h{maxh}__v1"
        s = summarize(g, nt, hd, rs, len(syms), cost)
        if s:
            res[tag] = s
    out = os.path.join(ROOT, "docs", f"minervini_sweep_results_{uni}_{interval}.json")
    json.dump({"results": res}, open(out, "w"), indent=1)
    for t, v in sorted(res.items()):
        print(t, v["pfnet_gross"], v["pfnet"], v["win_pct"], v["n"], v["avg_held_bars"])


if __name__ == "__main__":
    main_run()
