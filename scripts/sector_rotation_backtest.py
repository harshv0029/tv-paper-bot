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
MIN_SECTOR, BREADTH_HI, BREADTH_LO = 5, 0.6, 0.4
LS, NS, HS, KS = (1, 3, 5), (1, 3, 5), (1, 5, 10, 20), (0, 1.5, 2.5)  # k=0: no stop
if os.environ.get("KS"):  # wide disaster-stop sweep (B-348): KS="4,6"
    KS = tuple(float(x) for x in os.environ["KS"].split(","))
FADE = os.environ.get("FADE", "0") == "1"  # breadth-reversal: short the strongest sector, long the weakest
UNI = os.environ.get("UNI", "")  # "n200" = only the live swing watchlist (what the bot can actually trade)
VARIANT = ("fade" if FADE else "momentum") + ("_n200" if UNI == "n200" else "")
TF = os.environ.get("TF", "1d")  # 1d | 1h | 15m | 5m (4h owed: needs 1h resample)
PERIOD = {"1d": "5y", "1h": "730d", "4h": "730d", "15m": "60d", "5m": "60d"}[TF]
BAR_H = {"1d": 6.25, "1h": 1.0, "4h": 3.125, "15m": 0.25, "5m": 5 / 60}[TF]
if TF != "1d":  # holds in BARS: ~1 session, ~3 sessions, ~5 sessions of the tf
    per_day = round(6.25 / BAR_H)
    HS = (per_day, 3 * per_day, 5 * per_day)
OUT = os.path.join(ROOT, "docs", ("sector_rotation_results" if not FADE else "sector_rotation_fade_results") + ("" if TF == "1d" else f"_{TF}") + ("_wide" if os.environ.get("KS") else "") + ("_n200" if UNI == "n200" else "") + ".json")


def resample_4h(d):
    """1h panel (columns: field x symbol) -> two bars per NSE session: 09:15-13:15
    and 13:15-15:30 (the 4h candle yfinance does not serve; B-341)."""
    import pandas as pd
    ix = d.index
    local = ix.tz_convert("Asia/Kolkata") if ix.tz is not None else ix
    key = pd.Series(local.strftime("%Y-%m-%d") + np.where((local.hour * 60 + local.minute) < 13 * 60 + 15, "a", "b"), index=ix)
    first = d.groupby(key.values).head(1).index
    out = {}
    for f, how in (("Open", "first"), ("High", "max"), ("Low", "min"), ("Close", "last")):
        out[f] = d[f].groupby(key.values).agg(how)
    res = pd.concat(out, axis=1)
    res.index = [d.index[key.values == k][0] for k in res.index]
    return res.sort_index()


def load():
    import yfinance as yf
    sm = json.load(open(os.path.join(ROOT, "docs", "sector_map.json")))["map"]
    syms = sorted(sm)
    if UNI == "n200":
        import main as _m
        _w = set(_m.SWING_WATCHLIST)
        syms = [x for x in syms if x in _w]
        sm = {k: v for k, v in sm.items() if k in _w}
    fr = {f: [] for f in ("Open", "High", "Low", "Close")}
    idx = None
    got = []
    for i in range(0, len(syms), 100):
        b = syms[i:i + 100]
        d = yf.download(b, period=PERIOD, interval="1h" if TF == "4h" else TF, group_by="column", auto_adjust=True,
                        progress=False, threads=True)
        if d.empty:
            continue
        if TF == "4h":
            d = resample_4h(d)
        for s in b:
            try:
                if d["Close"][s].notna().sum() < (300 if TF == "1d" else 200):
                    continue
            except KeyError:
                continue
            got.append(s)
            for f in fr:
                fr[f].append(d[f][s])
        idx = d.index if idx is None else idx.union(d.index)
    arr = {f: np.column_stack([x.reindex(idx).values for x in v]) for f, v in fr.items()}
    # drop vendor glitch bars (bad prints produced fake +900% trades in the pattern lab, 2026-10-10 IST)
    O, H, L, C = arr["Open"], arr["High"], arr["Low"], arr["Close"]
    with np.errstate(invalid="ignore", divide="ignore"):
        bad = ~((O <= H * 1.001) & (O >= L * 0.999) & (C <= H * 1.001) & (C >= L * 0.999) & (L > 0) & (H / L < 1.6))
        pcl = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
        bad |= np.abs(C / pcl - 1) > 0.35
    for f in arr:
        arr[f] = np.where(bad, np.nan, arr[f])
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
            for x, d in ((best, "short" if FADE else "long"), (worst, "long" if FADE else "short")):
                if x is None:
                    continue
                mem = members[x]
                r = ret[t, mem]
                # momentum: strongest sector's top stocks / weakest sector's bottom stocks.
                # fade: strongest sector's top stocks are SHORTED, weakest sector's bottom are BOUGHT.
                order = np.argsort(-r if (d == "long") != FADE else r)
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
            tag = f"sector_rotation__{VARIANT}__{d}__{TF}__atr{ks}_h{Hh}_l{L}_n{N}__v1"
            res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                        "win_pct": round(float((pn > 0).mean() * 100), 1), "n": int(len(pn)),
                        "avg_net_pct": round(float(pn.mean() * 100), 3),
                        "avg_held_days": round(float(np.mean(held)) * BAR_H / 6.25, 2)}
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
