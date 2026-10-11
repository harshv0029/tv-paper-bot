"""VWAP 'Return to Value' failed-discovery (user video 2026-10-11), NSE intraday, both directions, 0.8% cost.
Session VWAP and volume-weighted sigma bands (k=1.5). Discovery = >=2 consecutive closes outside a band; failure = first close back inside.
Model A: enter at that close. Model B: limit at the band on a retest within 6 bars. Stop = discovery extreme; require RR to target >=1.5.
Targets: tp1 = VWAP, tp2 = opposite band (fixed at entry). Flat 15:15. Variants model {a,b} x target {tp1,tp2}. Env TF (5m|15m), UNI, MAXSYM.
Out docs/vwap_rtv_results_<TF>[_n200].json  tags vwap_rtv__<a|b>_<tp1|tp2>__<dir>__<tf>__k1d5_n2__v1"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TF = os.environ.get("TF", "5m"); UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", f"vwap_rtv_results_{TF}" + ("_n200" if UNI == "n200" else "") + ".json")
BPM = {"5m": 5, "15m": 15}[TF]; K = 1.5; NMIN = 2


def day_trades(o, h, l, c, v, side):
    """side +1 long (failed downside discovery), -1 short. Returns {variant: (ret, held)}."""
    n = len(c); tp_ = (h + l + c) / 3; cv = np.cumsum(v); cpv = np.cumsum(tp_ * v)
    vw = cpv / np.maximum(cv, 1); var = np.cumsum(tp_ ** 2 * v) / np.maximum(cv, 1) - vw ** 2
    sd = np.sqrt(np.maximum(var, 0)); up = vw + K * sd; lo = vw - K * sd
    out = {}; s = side; run = 0; ext = None
    for i in range(6, n - 1):
        if sd[i] / vw[i] < 0.002:
            continue
        outside = (c[i] < lo[i]) if s == 1 else (c[i] > up[i])
        if outside:
            run += 1; ext = min(ext, l[i]) if (s == 1 and ext is not None) else max(ext, h[i]) if (s == -1 and ext is not None) else (l[i] if s == 1 else h[i])
            continue
        if run >= NMIN and ext is not None:
            band = lo[i] if s == 1 else up[i]; opp = up[i] if s == 1 else lo[i]; mid = vw[i]
            sl = ext
            for mdl in ("a", "b"):
                if mdl == "a":
                    e, st = c[i], i + 1
                else:
                    e = None
                    for j in range(i + 1, min(n, i + 7)):
                        if (s == 1 and l[j] <= band) or (s == -1 and h[j] >= band):
                            e, st = band, j; break
                    if e is None:
                        continue
                for tg, tpv in (("tp1", mid), ("tp2", opp)):
                    if s * (tpv - e) <= 0 or s * (e - sl) <= 0 or s * (tpv - e) < 1.5 * s * (e - sl):
                        continue
                    x = None; m = st
                    for m in range(st, n):
                        stopped = (l[m] <= sl) if s == 1 else (h[m] >= sl)
                        if stopped:
                            x = (min(sl, o[m]) if s == 1 else max(sl, o[m])) if m > st or mdl == "a" else sl; break
                        if m > st or mdl == "a":
                            if (s == 1 and h[m] >= tpv) or (s == -1 and l[m] <= tpv):
                                x = tpv; break
                    if x is None:
                        m = n - 1; x = c[m]
                    out[f"{mdl}_{tg}"] = (s * (x - e) / e, m - st + 1)
            return out
        run = 0; ext = None
    return out


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = list(app._load_nse_universe_from_file())
    if UNI == "n200":
        syms = sorted(set(app.SWING_WATCHLIST) - set(app.ETF_SYMBOLS))
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    acc = {}
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period="60d", interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for sy in batch:
            try:
                df = (d[sy] if len(batch) > 1 else d).dropna(subset=["Close"])[["Open", "High", "Low", "Close", "Volume"]].dropna()
                idx = df.index.tz_convert("Asia/Kolkata") if df.index.tz is not None else df.index
            except Exception:
                continue
            if len(df) < 120:
                continue
            O, H, L, C, V = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
            days = np.array([t.date() for t in idx])
            for dy in sorted(set(days)):
                ii = np.where(days == dy)[0]
                if len(ii) < 12 or (C[ii] <= 0).any() or V[ii].sum() <= 0:
                    continue
                for side in (1, -1):
                    for k, (r, hl) in day_trades(O[ii], H[ii], L[ii], C[ii], V[ii], side).items():
                        a = acc.setdefault((k, side), [[], []]); a[0].append(r - cost); a[1].append(hl)
        print("batch", b0, flush=True)
    res = {}
    for (k, side), (rt, hl) in acc.items():
        r = np.array(rt)
        if len(r) < 30:
            print(k, side, "n", len(r), "too few"); continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        tag = f"vwap_rtv__{k}__{'long' if side == 1 else 'short'}__{TF}__k1d5_n2__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                    "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                    "avg_held_bars": round(float(np.mean(hl)), 2), "bar_hours": BPM / 60.0}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfnet_trim1"], m["win_pct"], m["n"], m["avg_net_pct"])


if __name__ == "__main__":
    main_run()
