"""Exhaustion Mean Theory (user video 2026-10-11): 5m (also 15m), session VWAP + 9 EMA, both directions, 0.8% cost.
Short: exhaustion bar = close stretched >= ext above BOTH VWAP and EMA9, upper wick >= 50% of range; trigger = NEXT bar trades below the
exhaustion low (entry at low, or open if gapped); stop = exhaustion high; target = VWAP (fixed at trigger). Long mirrored. Flat 15:15.
Sweep ext 0.5% / 1.0%. Env TF (5m|15m), UNI, MAXSYM. Out docs/emt_results_<TF>[_n200].json tags emt__vwap_ema9__<dir>__<tf>__ext0d5_wk50__v1"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TF = os.environ.get("TF", "5m"); UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", f"emt_results_{TF}" + ("_n200" if UNI == "n200" else "") + ".json")
BPM = {"5m": 5, "15m": 15}[TF]; EXTS = (0.005, 0.01); WICK = 0.5


def ema(x, n):
    k = 2 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def day_trades(o, h, l, c, v, side, ext):
    n = len(c); tp_ = (h + l + c) / 3; vw = np.cumsum(tp_ * v) / np.maximum(np.cumsum(v), 1); e9 = ema(c, 9)
    for i in range(6, n - 2):
        rg = h[i] - l[i]
        if rg <= 0:
            continue
        if side == -1:
            ok = c[i] >= vw[i] * (1 + ext) and c[i] >= e9[i] * (1 + ext) and (h[i] - max(o[i], c[i])) >= WICK * rg
            trig, sl, tp = l[i], h[i], vw[i]
            if not ok or tp >= trig:
                continue
        else:
            ok = c[i] <= vw[i] * (1 - ext) and c[i] <= e9[i] * (1 - ext) and (min(o[i], c[i]) - l[i]) >= WICK * rg
            trig, sl, tp = h[i], l[i], vw[i]
            if not ok or tp <= trig:
                continue
        j = i + 1
        if (side == -1 and l[j] > trig) or (side == 1 and h[j] < trig):
            continue  # not triggered on the confirmation bar
        e = min(trig, o[j]) if side == -1 else max(trig, o[j])
        x = None; m = j
        for m in range(j, n):
            if (side == -1 and h[m] >= sl) or (side == 1 and l[m] <= sl):
                x = sl; break
            if m > j and ((side == -1 and l[m] <= tp) or (side == 1 and h[m] >= tp)):
                x = tp; break
        if x is None:
            m = n - 1; x = c[m]
        return (-(x - e) / e if side == -1 else (x - e) / e), m - j + 1
    return None


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
                    for ext in EXTS:
                        r = day_trades(O[ii], H[ii], L[ii], C[ii], V[ii], side, ext)
                        if r:
                            a = acc.setdefault((ext, side), [[], []]); a[0].append(r[0] - cost); a[1].append(r[1])
        print("batch", b0, flush=True)
    res = {}
    for (ext, side), (rt, hl) in acc.items():
        r = np.array(rt)
        if len(r) < 30:
            print(ext, side, "n", len(r), "too few"); continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        tag = f"emt__vwap_ema9__{'long' if side == 1 else 'short'}__{TF}__ext{str(ext * 100).replace('.0', '').replace('.', 'd')}_wk50__v1"
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
