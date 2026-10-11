"""Fibonacci Golden Zone (0.618-0.79) + FVG pullback (user video 2026-10-11), both directions (short = reciprocal mirror), 0.8% cost.
Long: confirmed swing high H (pivot PV bars each side), swing low L = lowest low in the prior 60 bars, leg >= 6% (cost). Zone = H-0.618R .. H-0.79R.
Entry (close of the bar): low reaches zone, close > fib790 level, lower wick >= 0.8 x body, bullish candle. Variant fvg: a bullish 3-bar FVG inside the up-leg
overlapping the zone (top >= fib790 and bottom <= fib618), vs nofvg. SL = L, TP = H, max hold 30 bars, setup invalid if L breaks or H is reached first.
Env TF (1d|1h), UNI (n200|blank), MAXSYM. Out docs/fib_golden_results[_TF][_n200].json  tags fib_golden__<fvg|nofvg>__<dir>__<tf>__mh30_pv3__v1"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TF = os.environ.get("TF", "1d"); UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "fib_golden_results" + ("" if TF == "1d" else f"_{TF}") + ("_n200" if UNI == "n200" else "") + ".json")
PV, LOOK, MINLEG, MH, WAIT = 3, 60, 0.06, 30, 30
PERIOD = {"1d": "5y", "1h": "730d"}[TF]


def setups(o, h, l, c):
    """yield (kind, entry_idx, e, sl, tp) for long setups; kind in {fvg, nofvg}."""
    n = len(c); out = []; last_b = -1
    for b in range(PV, n - PV - 2):
        if h[b] != h[b - PV:b + PV + 1].max() or b <= last_b:
            continue
        a = max(0, b - LOOK) + int(np.argmin(l[max(0, b - LOOK):b]))
        H, L = h[b], l[a]; R = H - L
        if L <= 0 or R / L < MINLEG or a >= b - 1:
            continue
        z618, z79 = H - 0.618 * R, H - 0.79 * R
        fvg = any(l[k] > h[k - 2] and l[k] >= z79 and (h[k - 2] <= z618) for k in range(a + 2, b + 1))
        for j in range(b + PV + 1, min(n - 1, b + PV + WAIT)):
            if l[j] < L or h[j] >= H:
                break
            body = c[j] - o[j]
            wick = min(o[j], c[j]) - l[j]
            if l[j] <= z618 and c[j] > z79 and body > 0 and wick >= 0.8 * body:
                out.append(("fvg" if fvg else "nofvg", j, c[j], L, H, fvg)); last_b = b
                break
    return out


def walk(o, h, l, c, j, e, sl, tp):
    n = len(c); end = min(n - 1, j + MH)
    for m in range(j + 1, end + 1):
        if l[m] <= sl:
            return min(sl, o[m]) / e - 1, m - j
        if h[m] >= tp:
            return max(tp, o[m]) / e - 1 if o[m] > tp else tp / e - 1, m - j
    return c[end] / e - 1, end - j


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
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=PERIOD, interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = (d[s] if len(batch) > 1 else d).dropna(subset=["Close"])[["Open", "High", "Low", "Close"]].dropna()
            except Exception:
                continue
            if len(df) < 150 or (df.to_numpy() <= 0).any():
                continue
            O, H, L, C = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            for side in (1, -1):
                o, h, l, c = (O, H, L, C) if side == 1 else (1 / O, 1 / L, 1 / H, 1 / C)
                for kind, j, e, sl, tp, fvg in setups(o, h, l, c):
                    r, hd = walk(o, h, l, c, j, e, sl, tp)
                    real = r if side == 1 else 1 - 1 / (1 + r)
                    if abs(real) >= 0.4:
                        continue
                    for key in ({"fvg", "nofvg"} if fvg else {"nofvg"}):  # nofvg = every setup, fvg = FVG-confirmed subset
                        a = acc.setdefault((key, side), [[], []]); a[0].append(real - cost); a[1].append(hd)
        print("batch", b0, flush=True)
    res = {}
    for (key, side), (rt, hl) in acc.items():
        r = np.array(rt)
        if len(r) < 30:
            print(key, side, "n", len(r), "too few"); continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        tag = f"fib_golden__{key}__{'long' if side == 1 else 'short'}__{TF}__mh{MH}_pv{PV}__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                    "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                    "avg_held_bars": round(float(np.mean(hl)), 2), "bar_hours": 6.25 if TF == "1d" else 1.0}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfnet_trim1"], m["win_pct"], m["n"], m["avg_net_pct"], m["avg_held_bars"])


if __name__ == "__main__":
    main_run()
