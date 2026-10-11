"""Overnight anomaly (Knuteson night-vs-day) backtest, daily bars, both directions, ATR-stop sweep on the day legs.
night = buy close(t), sell open(t+1); day = open(t) -> close(t). Mirrors (night short, day long) are separate tags.
Overnight legs hold across a closed market so a resting stop cannot fire before the open: tested stopless
(gap risk only) and reported as such. Env: UNI (n200|etf|blank=full), MAXSYM. Out: docs/overnight_anomaly_results[_uni].json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "overnight_anomaly_results" + (f"_{UNI}" if UNI in ("n200", "etf") else "") + ".json")
KS = (0, 1.5, 2.5)


def atr_arr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) > n:
        cs = np.cumsum(np.r_[0, tr])
        out[n:] = (cs[n + 1:] - cs[1:len(c) - n + 1]) / n
    return out


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = list(app._load_nse_universe_from_file())
    if UNI == "n200":
        syms = sorted(set(app.SWING_WATCHLIST) - set(app.ETF_SYMBOLS))
    elif UNI == "etf":
        syms = sorted(app.ETF_SYMBOLS)
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    acc = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period="5y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close"]].dropna()
            except Exception:
                continue
            if len(df) < 120:
                continue
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            ok = (o > 0) & (c > 0)
            # night leg: C[t] -> O[t+1]
            night = o[1:] / c[:-1] - 1
            m = ok[1:] & ok[:-1] & (np.abs(night) < 0.4)  # drop split/bad-data jumps
            for side, nm in ((1, "long"), (-1, "short")):
                acc.setdefault(("night", nm, 0), []).append((side * night[m]) - cost)
            a = atr_arr(h, l, c)
            for k in KS:
                for side, nm in ((1, "long"), (-1, "short")):
                    if side == 1:
                        ex = np.where((k > 0) & (l <= o - k * a), np.minimum(o - k * a, o), c) if k else c
                        r = ex / o - 1
                    else:
                        ex = np.where((k > 0) & (h >= o + k * a), np.maximum(o + k * a, o), c) if k else c
                        r = 1 - ex / o
                    mm = ok & ~np.isnan(a) & (np.abs(r) < 0.4) if k else ok & (np.abs(r) < 0.4)
                    acc.setdefault(("day", nm, k), []).append(r[mm] - cost)
        print("batch", b0, flush=True)
    res = {}
    for (leg, nm, k), parts in acc.items():
        r = np.concatenate(parts)
        if len(r) < 30:
            continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        ks = "none" if not k else str(k).replace(".", "d")
        tag = f"overnight__{leg}__{nm}__1d__atr{ks}__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                    "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                    "avg_held_bars": 1.0, "bar_hours": 17.5 if leg == "night" else 6.25}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfnet_trim1"], m["win_pct"], m["n"], m["avg_net_pct"])


if __name__ == "__main__":
    main_run()
