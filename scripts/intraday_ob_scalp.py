"""Intraday liquidity-screen + morning Order Block retest scalp (user video 2026-10-11), 5m/15m, both directions.
Per symbol-day: first 30 min RVOL (vs prior-20-day same-window mean) and bias = sign(close@30min - open). Bias picks the
direction (long/short). OB = small-body bar followed by an impulse bar (body>=ATR, vol>=1.5x mean of last 20 bars) before 10:15.
Limit entry at OB boundary on retest (impulse+1 .. 11:30), SL beyond far side of OB - bf*ATR, exit on pin bar (wick>=2x body and
>=0.5% price) at its close, else time stop TO bars / 15:15. Variants: top3 = 3 highest-RVOL symbol-days per date (chosen before
any trade exists, no lookahead); all = every symbol-day. Env: TF (5m|15m), UNI (n200|blank), MAXSYM. Out docs/intraday_ob_scalp_results[_TF][_UNI].json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TF = os.environ.get("TF", "5m"); UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "intraday_ob_scalp_results" + ("" if TF == "5m" else f"_{TF}") + (f"_{UNI}" if UNI == "n200" else "") + ".json")
BPM = 5 if TF == "5m" else 15
SCREEN_BARS = 30 // BPM
OB_LAST = (60 + 15) // BPM; RETEST_LAST = (135 + 60) // BPM; TO = 60 // BPM + 6; BF = 0.5


def trade(o, h, l, c, v, a, side):
    """o..v for one day (plus warm-up arrays are pre-sliced by caller). side +1 long; -1 short via reciprocal mirror."""
    if side == -1:
        o, h, l, c = 1 / o, 1 / l, 1 / h, 1 / c
    n = len(c)
    for k in range(2, min(OB_LAST, n - 2)):
        rg = h[k - 1] - l[k - 1]
        if rg <= 0 or np.isnan(a[k]):
            continue
        if abs(c[k - 1] - o[k - 1]) > 0.5 * rg:
            continue
        body = c[k] - o[k]
        if body < a[k] or v[k] < 1.5 * max(v[:k].mean(), 1) or c[k] <= h[k - 1]:
            continue
        zone = h[k - 1]; sl = l[k - 1] - BF * a[k]
        if zone <= sl:
            continue
        for j in range(k + 1, min(n, RETEST_LAST)):
            if l[j] <= zone:
                e = min(zone, o[j])
                if e <= sl:
                    return None
                x = None; end = min(n - 1, j + TO)
                for m in range(j, end + 1):
                    if l[m] <= sl and m > j or (m == j and l[m] <= sl):
                        x = sl; break
                    bd = abs(c[m] - o[m]); uw = h[m] - max(c[m], o[m])
                    if m > j and uw >= 2 * bd and uw >= 0.005 * c[m]:
                        x = c[m]; break
                if x is None:
                    x = c[end]; m = end
                return x / e - 1, m - j + 1
        return None
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
    rows = []  # (date, rvol, side, ret or None, held)
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period="60d", interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = (d[s] if len(batch) > 1 else d).dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                idx = df.index.tz_convert("Asia/Kolkata") if df.index.tz is not None else df.index
            except Exception:
                continue
            if len(df) < 200:
                continue
            o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
            pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
            a = np.convolve(tr, np.ones(14) / 14, "full")[:len(tr)]; a[:14] = np.nan
            days = np.array([t.date() for t in idx]); hist = []
            for dy in sorted(set(days)):
                ii = np.where(days == dy)[0]
                if len(ii) < OB_LAST + 4:
                    continue
                sv = v[ii[:SCREEN_BARS]].sum()
                if len(hist) >= 5 and np.mean(hist[-20:]) > 0:
                    rv = sv / np.mean(hist[-20:])
                    bias = c[ii[SCREEN_BARS - 1]] - o[ii[0]]
                    side = 1 if bias > 0 else -1
                    # trade window starts after the screen: bars from the day open (OB can use pre-screen bars only up to knowledge time; entry after screen)
                    r = trade(o[ii], h[ii], l[ii], c[ii], v[ii], a[ii], side)
                    rows.append((str(dy), float(rv), side, None if r is None else (r[0] if side == 1 else 1 - 1 / (1 + r[0])) , None if r is None else r[1]))
                hist.append(sv)
        print("batch", b0, len(rows), flush=True)
    res = {}
    byday = {}
    for rw in rows:
        byday.setdefault(rw[0], []).append(rw)
    sel = {"top3": [r for dy in byday.values() for r in sorted(dy, key=lambda x: -x[1])[:3]], "all": rows}
    for var, lst in sel.items():
        for side, nm in ((1, "long"), (-1, "short")):
            pr = [(r[3], r[4]) for r in lst if r[2] == side and r[3] is not None]
            if len(pr) < 30:
                print(var, nm, "n", len(pr), "too few"); continue
            r = np.array([x[0] for x in pr]) - cost
            gain, loss = r[r > 0].sum(), -r[r < 0].sum()
            rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
            tag = f"ob_scalp__{'screen_top3' if var == 'top3' else 'unscreened'}__{nm}__{TF}__bf0d5_to{TO}__v1"
            res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                        "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                        "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                        "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                        "avg_held_bars": round(float(np.mean([x[1] for x in pr])), 2), "bar_hours": BPM / 60.0}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in res.items():
        print(t, m["pfnet"], m["pfnet_trim1"], m["win_pct"], m["n"], m["avg_net_pct"])


if __name__ == "__main__":
    main_run()
