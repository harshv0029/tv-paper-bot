"""Out-of-sample check of the best combo_lab cells (B-18).

combo_lab scans thousands of ordered pairs on the live swing universe, so its best in-sample cells are
inflated by multiple testing. This script re-runs the top cells (long, ATR-6 stop, in-sample trimmed PFnet
>= 1.3, n >= 300) on symbols the lab never saw: a seeded sample of the full NSE universe minus the swing
watchlist. Only cells that still clear PFnet 1 (trimmed) out of sample are registered with metrics; the rest
keep their in-sample numbers as evidence only (metrics=None -> not viable).
Output docs/combo_validate_results.json keyed by the SAME tag as combo_lab_results.json.
"""
import importlib.util
import json
import os
import random
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["UNI"] = "n200"
spec = importlib.util.spec_from_file_location("combo_lab", os.path.join(ROOT, "scripts", "combo_lab.py"))
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)
pl = cl.pl
OUT = os.path.join(ROOT, "docs", "combo_validate_results.json")
TOP = int(os.environ.get("TOP_CELLS", "80"))
SAMPLE = int(os.environ.get("OOS_SYMBOLS", "500"))


def parse(tag):
    # combo__<A>_x_<B>__<dir>__1d__atr<k>_h<H>__v1 ; rule names contain single underscores only
    p = tag.split("__")
    a, b = p[1].split("_x_")
    k, h = p[4][3:].split("_h")
    return a, b, p[2], (0 if k == "none" else float(k)), int(h)


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    cells = json.load(open(os.path.join(ROOT, "docs", "combo_lab_results.json")))["results"]
    cand = sorted([(min(m["pfnet"], m["pfnet_trim1"] or m["pfnet"]), t) for t, m in cells.items()
                   if m["pfnet"] and m["n"] >= 300 and "__long__" in t and "__atr6_" in t], reverse=True)
    cand = [t for pf, t in cand if pf >= 1.3][:TOP]
    print("cells to validate", len(cand), flush=True)
    seen = set(app.SWING_WATCHLIST)
    pool = [s for s in app._load_nse_universe_from_file() if s not in seen and s not in app.ETF_SYMBOLS]
    random.Random(7).shuffle(pool)
    pool = pool[:SAMPLE]
    acc = {t: [[], []] for t in cand}
    # rule names as stored in tags have '__' collapsed to '_': map back to the lab's rule keys
    rule_keys = None
    done = 0
    for b0 in range(0, len(pool), 100):
        batch = pool[b0:b0 + 100]
        try:
            d = yf.download(batch, period="5y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex)
            continue
        for s in batch:
            try:
                df = pl.clean_bars(d[s].dropna(subset=["Close"])[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) < 200:
                continue
            sigs = pl.all_signals(df)
            norm = {k.replace("__", "_"): k for k in sigs}
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            atr = pl.atr_arr(h, l, c)
            for t in cand:
                a, b, dname, k, H = parse(t)
                if a not in norm or b not in norm:
                    continue
                trig = np.asarray(sigs[norm[a]][0], bool)
                flt = cl.near(np.asarray(sigs[norm[b]][0], bool))
                comb = trig & flt
                if not comb.any():
                    continue
                r, hd = pl.simulate(comb, o, h, l, c, atr, H, k, cost, 1)
                if r:
                    acc[t][0].extend(r)
                    acc[t][1].extend(hd)
            done += 1
        print("oos symbols", done, flush=True)
    res = {}
    for t, (r, hd) in acc.items():
        if len(r) < 100:
            continue
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r)
        tr = rs[:-max(1, int(len(rs) * 0.01))]
        tl = -tr[tr < 0].sum()
        res[t] = {"pfnet": round(float(g / lo), 3) if lo else None, "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                  "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)), "avg_net_pct": round(float(r.mean() * 100), 3),
                  "median_net_pct": round(float(np.median(r) * 100), 3), "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25,
                  "oos_symbols": done}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    ok = sorted([(min(m["pfnet"], m["pfnet_trim1"] or m["pfnet"]), m["n"], t) for t, m in res.items() if m["pfnet"]], reverse=True)
    print("validated cells", len(res), "oos pfnet>1:", sum(1 for x in ok if x[0] > 1))
    for x in ok[:25]:
        print(x)


if __name__ == "__main__":
    main_run()
