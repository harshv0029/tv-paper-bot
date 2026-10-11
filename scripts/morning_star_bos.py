"""Supply & Demand Morning Star + Break of Structure, retest entry (video 2026-10-11). Both directions.
Long: downtrend (lower highs/lows) -> support tap -> morning star (bearish c1, star body<=BR of range, bullish c3 closing
above c1 midpoint) -> BOS (close above last lower high within 2 bars) -> limit buy at star high, expires N bars after BOS ->
SL star low - BF*ATR, TP supply origin (highest high before c1), min reward:risk RR. Short mirror = evening star + bearish BOS.
Sweeps BF (ATR buffer) x RR x candle size (TF env 1d|1h|15m|5m). Env: UNI (n200|etf|blank=full), MAXSYM.
Out: docs/morning_star_bos_results[_TF][_UNI].json (pattern_lab schema)."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
UNI = os.environ.get("UNI", ""); TF = os.environ.get("TF", "1d")
PERIOD = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}[TF]
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "morning_star_bos_results" + ("" if TF == "1d" else f"_{TF}") + (f"_{UNI}" if UNI in ("n200", "etf") else "") + ".json")
BR, PIV, TAP_LB, SUPPLY_LB, RETEST_N, MAXHOLD = 0.35, 3, 20, 20, 15, 30
BFS, RRS = (0.0, 0.5), (1.5, 2.0)


def atr_arr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) > n:
        cs = np.cumsum(np.r_[0, tr]); out[n:] = (cs[n + 1:] - cs[1:len(c) - n + 1]) / n
    return out


def pivots(x, hi=True, k=PIV):
    """index list of confirmed pivots (confirmed k bars later)."""
    out = []
    for i in range(k, len(x) - k):
        w = x[i - k:i + k + 1]
        if (hi and x[i] == w.max() and (w == x[i]).sum() == 1) or ((not hi) and x[i] == w.min() and (w == x[i]).sum() == 1):
            out.append(i)
    return out


def run(o, h, l, c, a, cost, side, bf, rr):
    """side +1 long (morning star), -1 short (evening star, mirrored by flipping the series)."""
    if side == -1:
        o, h, l, c = 1 / o, 1 / l, 1 / h, 1 / c  # reciprocal mirror keeps ratios; flips highs/lows
        # note: reciprocal series so a short on price == long on 1/price (as in the MCX sweep)
    n = len(c); rets, held = [], []
    ph = pivots(h, True); pl = pivots(l, False)
    phs = np.array(ph); pls = np.array(pl)
    i = 2 * PIV + TAP_LB
    while i < n - 2:
        r = h[i - 2] - l[i - 2]; r2 = h[i - 1] - l[i - 1]; r3 = h[i] - l[i]
        if r <= 0 or r2 <= 0 or r3 <= 0 or np.isnan(a[i]):
            i += 1; continue
        b1 = o[i - 2] - c[i - 2]; body2 = abs(c[i - 1] - o[i - 1]); b3 = c[i] - o[i]
        mid1 = (o[i - 2] + c[i - 2]) / 2
        if not (b1 >= 0.6 * r and c[i - 2] <= l[i - 2] + 0.3 * r and body2 <= BR * r2 and b3 >= 0.5 * r3 and c[i] > mid1):
            i += 1; continue
        # context: confirmed pivots before c1 (confirmed by bar i-2): lower highs and lower lows
        pk = phs[phs <= i - 2 - PIV]; pq = pls[pls <= i - 2 - PIV]
        if len(pk) < 2 or len(pq) < 2 or not (h[pk[-1]] < h[pk[-2]] and l[pq[-1]] < l[pq[-2]]):
            i += 1; continue
        if l[i - 1] > l[max(0, i - 1 - TAP_LB):i - 1].min() + 0.25 * a[i]:  # star taps the recent swing low
            i += 1; continue
        lh = h[pk[-1]]  # most recent lower high
        bos = None
        for j in (i, i + 1):
            if j < n and c[j] > lh:
                bos = j; break
        if bos is None:
            i += 1; continue
        zone = h[i - 1]; sl = l[i - 1] - bf * a[i]; tp = h[max(0, i - 2 - SUPPLY_LB):i - 2].max()
        if zone <= sl or (tp - zone) < rr * (zone - sl):
            i += 1; continue
        fill = None
        for j in range(bos + 1, min(n, bos + 1 + RETEST_N)):
            if h[j] >= tp:
                break  # reached the target before the retest: order cancelled
            if l[j] <= zone:
                fill = j; break
        if fill is None:
            i = bos + 1; continue
        e = min(zone, o[fill]); x = None; j = fill
        end = min(n, fill + MAXHOLD)
        while j < end:
            if l[j] <= sl:
                x = min(sl, o[j]) if j > fill else sl; break
            if h[j] >= tp and j > fill:
                x = tp; break
            j += 1
        if x is None:
            j = end - 1; x = c[j]
        rets.append(x / e - 1 - cost); held.append(j - fill + 1)
        i = j + 1
    return rets, held


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
            d = yf.download(batch, period=PERIOD, interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close"]].dropna()
            except Exception:
                continue
            if len(df) < 120:
                continue
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            if (o <= 0).any() or (c <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():
                continue  # vendor glitch / split: skip the symbol rather than trust it
            a = atr_arr(h, l, c)
            for side, nm in ((1, "long"), (-1, "short")):
                for bf in BFS:
                    for rr in RRS:
                        r, hd = run(o, h, l, c, a if side == 1 else atr_arr(1 / l, 1 / h, 1 / c), cost, side, bf, rr)
                        if r:
                            x = acc.setdefault((nm, bf, rr), [[], []]); x[0].extend(r); x[1].extend(hd)
        print("batch", b0, flush=True)
    res = {}
    for (nm, bf, rr), (r, hd) in acc.items():
        if len(r) < 30:
            continue
        r = np.array(r); gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        fam = "morning_star_bos" if nm == "long" else "evening_star_bos"
        tag = f"{fam}__retest__{nm}__{TF}__bf{str(bf).replace('.', 'd')}_rr{str(rr).replace('.', 'd')}__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                    "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                    "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": {"1d": 6.25, "1h": 1.0, "15m": 0.25, "5m": 5 / 60}[TF]}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m["pfnet"], m["pfnet_trim1"], m["win_pct"], m["n"], m["avg_net_pct"])


if __name__ == "__main__":
    main_run()
