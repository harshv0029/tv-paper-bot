"""B-336: sector/industry rotation research, daily bars, both directions.

Each day t (signal at close): per sector (docs/sector_map.json, >= MIN_SECTOR
stocks with data) compute breadth (share of stocks up over L days) and mean L-day
return. LONG: strongest sector with breadth >= BREADTH_HI, buy its top-N stocks by
L-day return. SHORT: weakest sector with breadth <= BREADTH_LO, short its bottom-N.
Entry at next open, exit after H days at close or at an ATR(14) stop on the daily
low/high. Cost = main.ROUND_TRIP_COST_PCT per round trip. Each daily signal is an
independent trade (PF is per trade; overlap noted). Daily timeframe only: intraday
(1h/15m/5m) and 4h are owed. Output docs/sector_rotation_results.json."""
import json, os, sys, time, itertools
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MIN_SECTOR, BREADTH_HI, BREADTH_LO = 8, 0.6, 0.4
LS, NS, HS, KS = (1, 3, 5), (1, 3, 5), (1, 5, 10, 20), (0, 1.5, 2.5)  # k=0: no stop
OUT = os.path.join(ROOT, "docs", "sector_rotation_results.json")


def load():
    import yfinance as yf
    sm = json.load(open(os.path.join(ROOT, "docs", "sector_map.json")))["map"]
    syms = sorted(sm)
    fr = {f: [] for f in ("Open", "High", "Low", "Close")}
    idx = None
    got = []
    for i in range(0, len(syms), 100):
        b = syms[i:i + 100]
        d = yf.download(b, period="5y", interval="1d", group_by="column", auto_adjust=True,
                        progress=False, threads=True)
        if d.empty:
            continue
        for s in b:
            try:
                if d["Close"][s].notna().sum() < 300:
                    continue
            except KeyError:
                continue
            got.append(s)
            for f in fr:
                fr[f].append(d[f][s])
        idx = d.index if idx is None else idx.union(d.index)
    arr = {f: np.column_stack([x.reindex(idx).values for x in v]) for f, v in fr.items()}
    return got, sm, idx, arr


def main():
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms, sm, idx, A = load()
    O, H_, L_, C = A["Open"], A["High"], A["Low"], A["Close"]
    T, S = C.shape
    sec = np.array([sm[s]["sector"] for s in syms])
    secs = [x for x in sorted(set(sec)) if (sec == x).sum() >= MIN_SECTOR]
    members = {x: np.where(sec == x)[0] for x in secs}
    pc = np.vstack([np.full((1, S), np.nan), C[:-1]])
    tr = np.maximum(H_ - L_, np.maximum(abs(H_ - pc), abs(L_ - pc)))
    atr = np.full((T, S), np.nan)
    for t in range(14, T):
        atr[t] = np.nanmean(tr[t - 13:t + 1], axis=0)
    # picks[(L,N,dir)] -> list of (t, stock idx) signals
    picks = {}
    for L in LS:
        ret = np.full((T, S), np.nan)
        ret[L:] = C[L:] / C[:-L] - 1
        for t in range(L + 15, T - 2):
            best = worst = None
            bs = ws = None
            for x in secs:
                r = ret[t, members[x]]
                ok = ~np.isnan(r)
                if ok.sum() < MIN_SECTOR:
                    continue
                br, m = (r[ok] > 0).mean(), r[ok].mean()
                if br >= BREADTH_HI and (bs is None or m > bs):
                    bs, best = m, x
                if br <= BREADTH_LO and (ws is None or m < ws):
                    ws, worst = m, x
            for x, d in ((best, "long"), (worst, "short")):
                if x is None:
                    continue
                mem = members[x]
                r = ret[t, mem]
                order = np.argsort(-r if d == "long" else r)
                for N in NS:
                    for j in [mem[k] for k in order[:N] if not np.isnan(r[k])]:
                        picks.setdefault((L, N, d), []).append((t, j))
    res = {}
    for (L, N, d), sigs in picks.items():
        for Hh, k in itertools.product(HS, KS):
            pn = []
            held = []
            for t, j in sigs:
                e = t + 1
                if e + Hh >= T or np.isnan(O[e, j]) or np.isnan(atr[t, j]):
                    continue
                ent = O[e, j]
                stop = None
                if k:
                    stop = ent - k * atr[t, j] if d == "long" else ent + k * atr[t, j]
                exitp, hd = C[e + Hh - 1, j], Hh
                for q in range(Hh):
                    tt = e + q
                    if stop is not None and ((d == "long" and L_[tt, j] <= stop) or (d == "short" and H_[tt, j] >= stop)):
                        exitp, hd = stop, q + 1
                        break
                if np.isnan(exitp):
                    continue
                g = (exitp / ent - 1) * (1 if d == "long" else -1)
                pn.append(g - cost)
                held.append(hd)
            if len(pn) < 30:
                continue
            pn = np.array(pn)
            gain, loss = pn[pn > 0].sum(), -pn[pn < 0].sum()
            ks = "none" if not k else str(k).replace(".", "d")
            tag = f"sector_rotation__momentum__{d}__1d__atr{ks}_h{Hh}_l{L}_n{N}__v1"
            res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                        "win_pct": round(float((pn > 0).mean() * 100), 1), "n": int(len(pn)),
                        "avg_net_pct": round(float(pn.mean() * 100), 3),
                        "avg_held_days": round(float(np.mean(held)), 2)}
    json.dump({"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "symbols": len(syms), "sectors": len(secs), "bars": T, "cost_pct": cost * 100,
               "results": res}, open(OUT, "w"), indent=0)
    top = sorted(res.items(), key=lambda kv: -(kv[1]["pfnet"] or 0))[:10]
    print(f"cells={len(res)} symbols={len(syms)} sectors={len(secs)}")
    for dd in ("long", "short"):
        v = [r for t, r in res.items() if f"__{dd}__" in t and r["pfnet"]]
        print(dd, "cells", len(v), "viable(>=1.0)", sum(r["pfnet"] >= 1.0 for r in v))
    for t, r in top:
        print(t, r)


if __name__ == "__main__":
    main()
