"""Indicator combinatorics Step 2 (B-18): ordered trigger x filter pairs of the pattern-lab rules.

A pair (A, B) fires when A (the trigger event) is true on bar t AND B (the filter state) was true on at
least one of bars t-2..t. Both role orderings are separate strategies. Both directions. Hold 10/20 bars,
ATR stop none or 6x. Same data, cleaning, cost and non-overlap simulation as scripts/pattern_lab.py, on the
live swing universe (stocks of SWING_WATCHLIST). Rules are limited to the TOP_RULES most frequent ones so
the pair count stays tractable (60 rules -> 3,540 ordered pairs); this prioritisation is disclosed, not
silent. Output docs/combo_lab_results.json, tags
combo__<A>_x_<B>__<dir>__1d__atr<k>_h<H>__v1.
"""
import importlib.util
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["UNI"] = "n200"
spec = importlib.util.spec_from_file_location("pattern_lab", os.path.join(ROOT, "scripts", "pattern_lab.py"))
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

TOP_RULES = int(os.environ.get("TOP_RULES", "60"))
HOLDS = (10, 20)
KS = (0, 6)
OUT = os.path.join(ROOT, "docs", "combo_lab_results.json")


def near(sig, k=2):
    """True if sig fired on any of the last k+1 bars."""
    out = sig.copy()
    for j in range(1, k + 1):
        out[j:] |= sig[:-j]
    return out


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = sorted(set(app.SWING_WATCHLIST) - set(app.ETF_SYMBOLS))
    frames = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
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
            if len(df) >= 200:
                frames[s] = df
        print("download", b0, len(frames), flush=True)
    return run_on_frames(frames, cost)


def run_on_frames(frames, cost):
    # pass 1: fire counts per rule/dir to choose the rule set
    counts = {}
    cache = {}
    for s, df in frames.items():
        sigs = pl.all_signals(df)
        cache[s] = sigs
        for r, (lg, sh) in sigs.items():
            if r.startswith("baseline"):
                continue
            c = counts.setdefault(r, [0, 0])
            c[0] += int(np.sum(lg))
            c[1] += int(np.sum(sh))
    keep = [r for r, _ in sorted(counts.items(), key=lambda kv: -(min(kv[1]) + 0.001 * max(kv[1])))][:TOP_RULES]
    print("rules kept", len(keep), flush=True)
    acc = {}
    for s, df in frames.items():
        o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
        atr = pl.atr_arr(h, l, c)
        sigs = cache[s]
        nearcache = {r: (near(np.asarray(sigs[r][0], bool)), near(np.asarray(sigs[r][1], bool))) for r in keep if r in sigs}
        for a in keep:
            if a not in sigs:
                continue
            for b in keep:
                if a == b or b not in sigs:
                    continue
                for di, (dname, side) in enumerate((("long", 1), ("short", -1))):
                    trig = np.asarray(sigs[a][di], bool)
                    if not trig.any():
                        continue
                    comb = trig & nearcache[b][di]
                    if not comb.any():
                        continue
                    for H in HOLDS:
                        for k in KS:
                            r, hd = pl.simulate(comb, o, h, l, c, atr, H, k, cost, side)
                            if r:
                                x = acc.setdefault((a, b, dname, H, k), [[], []])
                                x[0].extend(r)
                                x[1].extend(hd)
    res = {}
    for (a, b, dname, H, k), (r, hd) in acc.items():
        if len(r) < 300:  # inconclusive below n=300; the result file stays a pass-or-fail record of every cell above it
            continue
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r)
        tr = rs[:-max(1, int(len(rs) * 0.01))]
        tl = -tr[tr < 0].sum()
        ks = "none" if not k else str(k)
        fa, fb = a.replace("__", "_"), b.replace("__", "_")
        res[f"combo__{fa}_x_{fb}__{dname}__1d__atr{ks}_h{H}__v1"] = {
            "pfnet": round(float(g / lo), 3) if lo else None,
            "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
            "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
            "avg_net_pct": round(float(r.mean() * 100), 3), "median_net_pct": round(float(np.median(r) * 100), 3),
            "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}
    json.dump({"results": res}, open(OUT, "w"), indent=0) if OUT else None
    print("cells", len(res))
    good = sorted([(min(m["pfnet"], m["pfnet_trim1"] or m["pfnet"]), m["n"], t) for t, m in res.items()
                   if m["pfnet"] and m["n"] >= 300], reverse=True)
    for x in good[:30]:
        print(x)
    return res


if __name__ == "__main__":
    main_run()
