"""Intermarket timing of NIFTY (B-149..B-154, B-156, B-160, B-161), both directions.

Reference series (yfinance): USDINR (INR=X), S&P 500 (^GSPC), US 10y yield (^TNX, the bond proxy: India G-sec
history is unavailable), crude (CL=F), gold (GC=F), dollar index (DX-Y.NYB), VIX (^VIX), India VIX (^INDIAVIX).
For each reference: events = cross of the reference over/under its 50-day MA, and a 60-day rolling correlation
state; each event is a long AND a short NIFTY signal (so both directions of every relation are measured).
Signal at close t -> NIFTY entry next open -> exit after H bars at the close (or ATR stop). Net of
main.ROUND_TRIP_COST_PCT. Tags intermarket__<ref>_<event>__<dir>__1d__atr<k>_h<H>__v1. Output
docs/intermarket_lab_results.json.
"""
import importlib.util
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location("breadth_lab", os.path.join(ROOT, "scripts", "breadth_lab.py"))
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)
OUT = os.path.join(ROOT, "docs", "intermarket_lab_results.json")
REFS = {"usdinr": "INR=X", "spx": "^GSPC", "us10y": "^TNX", "crude": "CL=F", "gold": "GC=F", "dxy": "DX-Y.NYB", "vix": "^VIX", "indiavix": "^INDIAVIX"}
HOLDS = (5, 10, 20)
KS = (0, 2.5)


def dl(tk):
    import yfinance as yf
    d = yf.download(tk, period="6y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.dropna(subset=["Close"])
    d.index = pd.DatetimeIndex(d.index).tz_localize(None)
    return d


def main_run():
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    nifty = bl.clean(dl("^NSEI")[["Open", "High", "Low", "Close"]].dropna())
    ix = nifty.index
    ic = nifty["Close"]
    o, h, l, c = (nifty[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    pc = np.roll(c, 1)
    atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
    res = {}

    def put(tag, r, hd):
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        res[tag] = {"pfnet": round(float(g / lo), 3) if lo else None, "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 3), "median_net_pct": round(float(np.median(r) * 100), 3),
                    "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}

    def run(name, ev):
        ev = np.asarray(ev.reindex(ix).fillna(False), bool)
        if ev.sum() < 5:
            return
        for dname, side in (("long", 1), ("short", -1)):
            for H in HOLDS:
                for k in KS:
                    r, hd = bl.simulate(ev, o, h, l, c, atr, H, k, cost, side)
                    if len(r) >= 20:
                        put(f"intermarket__{name}__{dname}__1d__atr{'none' if not k else str(k).replace('.', 'd')}_h{H}__v1", r, hd)

    got = []
    for nm, tk in REFS.items():
        try:
            s = dl(tk)["Close"].reindex(ix, method="ffill")
        except Exception as ex:
            print("ref fail", nm, ex)
            continue
        if s.dropna().shape[0] < 500:
            continue
        got.append(nm)
        ma = s.rolling(50).mean()
        run(f"{nm}_cross_above_ma50", bl.cross_up(s, ma))
        run(f"{nm}_cross_below_ma50", bl.cross_dn(s, ma))
        ret_ref, ret_n = s.pct_change(), ic.pct_change()
        corr = ret_ref.rolling(60).corr(ret_n)
        up20 = s > s.shift(20)
        run(f"{nm}_corr_neg_and_up", (corr < -0.3) & up20 & ~((corr < -0.3) & up20).shift(1).fillna(False))
        run(f"{nm}_corr_pos_and_up", (corr > 0.3) & up20 & ~((corr > 0.3) & up20).shift(1).fillna(False))
    # baseline
    allb = np.ones(len(c), bool)
    for dname, side in (("long", 1), ("short", -1)):
        for H in HOLDS:
            r, hd = bl.simulate(allb, o, h, l, c, atr, H, 0, cost, side)
            if len(r) >= 20:
                put(f"intermarket__baseline_every_bar__{dname}__1d__atrnone_h{H}__v1", r, hd)
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    print("refs", got, "cells", len(res))
    for t, m in sorted(res.items(), key=lambda kv: -(kv[1]["pfnet"] or 0))[:25]:
        print(t, m["pfnet"], m["n"])


if __name__ == "__main__":
    main_run()
