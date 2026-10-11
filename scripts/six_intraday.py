"""Six chart-pattern prompts (user screenshots 2026-10-11) adapted to NSE, both directions, 0.8% cost, NIFTY200/full via UNI.
TF=5m: silver_bullet (sweep prior-day hi/lo + FVG, limit at gap midpoint, 10:00-11:00 window start), orb (first 15 min, scale out half
at 1x range, trail rest 0.5x range), fvg_fill (15m-trend FVG retrace, 9:30-11:30, half at prior swing). TF=15m: gap_fill (>=0.5% gap fade,
tp prior close, sl 1x gap, flat 12:00), ob_retest (swing-break order block limit). TF=1h: ema_cross 9/21 (swing-10 stop, BE at 1R).
Shorts are the reciprocal-price mirror. Env TF, UNI (n200|blank), MAXSYM. Out docs/six_strat_results_<TF>[_n200].json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TF = os.environ.get("TF", "5m"); UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", f"six_strat_results_{TF}" + ("_n200" if UNI == "n200" else "") + ".json")
BPM = {"5m": 5, "15m": 15, "1h": 60}[TF]
FAM = {"silver_bullet": ("sweep_fvg", "5m", "w45to105"), "orb": ("first15_scaleout", "5m", "tr0d5"),
       "fvg_fill": ("trend_retrace", "5m", "w15to135"), "gap_fill": ("half_fade", "15m", "g0d5"),
       "ob_retest": ("swing_break", "15m", "tmo20"), "ema_cross": ("e9_21", "1h", "sw10")}


def walk(o, h, l, c, start, e, sl, tp, end):
    """long-only walk from bar `start` (entry bar). returns (ret, held). stop wins ties on the entry bar."""
    for m in range(start, end + 1):
        if l[m] <= sl:
            return (min(sl, o[m]) if m > start else sl) / e - 1, m - start + 1
        if m > start and h[m] >= tp:
            return tp / e - 1, m - start + 1
    return c[end] / e - 1, end - start + 1


def silver_bullet(o, h, l, c, pdh, pdl):
    n = len(c); w0, w1 = 45 // BPM, 105 // BPM; lim = min(n - 2, 285 // BPM)
    if pdl is None:
        return None
    for s in range(w0, min(w1, n - 3) + 1):
        if l[s] < pdl:
            for k in range(s + 1, min(w1, n - 2) + 1):
                if l[k] > h[k - 2] and k - 2 >= s - 1:
                    mid = (h[k - 2] + l[k]) / 2; sl = l[s:k + 1].min()
                    if mid <= sl or pdh <= mid:
                        continue
                    for j in range(k + 1, lim + 1):
                        if h[j] >= pdh:
                            return None
                        if l[j] <= mid:
                            e = min(mid, o[j])
                            if e <= sl:
                                return None
                            return walk(o, h, l, c, j, e, sl, pdh, n - 1)
                    return None
    return None


def orb(o, h, l, c):
    n = len(c); R = 15 // BPM
    if n <= R + 2:
        return None
    hi, lo = h[:R].max(), l[:R].min(); ht = hi - lo
    for k in range(R, n - 1):
        if c[k] > hi and ht > 0:
            e = c[k]; sl = lo; tp1 = e + ht; half = False; hw = h[k]; x = None
            for m in range(k + 1, n):
                if not half:
                    if l[m] <= sl:
                        x = min(sl, o[m]); return (x / e - 1), m - k
                    if h[m] >= tp1:
                        half = True; hw = h[m]; st = max(sl, hw - 0.5 * ht)
                else:
                    if l[m] <= st:
                        x = min(st, o[m]); return 0.5 * (tp1 / e - 1) + 0.5 * (x / e - 1), m - k
                    hw = max(hw, h[m]); st = max(st, hw - 0.5 * ht)
            if half:
                return 0.5 * (tp1 / e - 1) + 0.5 * (c[-1] / e - 1), n - 1 - k
            return c[-1] / e - 1, n - 1 - k
        if c[k] < lo:
            return "short"  # handled by mirror run
    return None


def gap_fill(o, h, l, c, pc):
    n = len(c)
    if pc is None or n < 4:
        return None
    gap = pc - o[0]
    if gap / pc < 0.005:
        return None
    sl = o[0] - gap; end = min(n - 1, 165 // BPM)
    return walk(o, h, l, c, 0, o[0], sl, pc, end)


def ob_retest(o, h, l, c):
    n = len(c); P = 2
    for b in range(7, n - 2):
        ph = [i for i in range(P, b - P) if h[i] == h[i - P:i + P + 1].max()]
        if not ph:
            continue
        p = ph[-1]
        if not (c[b] > h[p] and c[b - 1] <= h[p]):
            continue
        s = max(0, b - 12) + int(np.argmin(l[max(0, b - 12):b + 1]))
        if s >= b:
            continue
        idx = next((i for i in range(min(s + 1, b - 1), max(0, s - 3) - 1, -1) if c[i] < o[i]), None)
        if idx is None:
            continue
        top, sl, tp = h[idx], l[idx], h[s:b + 1].max()
        if not (sl < top < tp):
            continue
        for j in range(b + 1, min(n - 1, b + 20) + 1):
            if h[j] >= tp:
                return None
            if l[j] <= top:
                e = min(top, o[j])
                if e <= sl:
                    return None
                return walk(o, h, l, c, j, e, sl, tp, n - 1)
        return None
    return None


def fvg_fill(o, h, l, c):
    n = len(c); w0, w1 = 15 // BPM, 135 // BPM
    for k in range(max(3, w0, 6), min(w1, n - 3) + 1):
        if l[k] > h[k - 2] and c[k] > c[k - 3] > c[k - 6]:
            top, bot = l[k], h[k - 2]; swing = h[max(0, k - 12):k].max()
            if swing <= top:
                continue
            for j in range(k + 1, min(n - 1, w1 + 12)):
                if l[j] <= top:
                    e = min(top, o[j])
                    if e <= bot:
                        return None
                    half = False; x2 = None
                    for m in range(j, n):
                        if l[m] <= bot:
                            x = min(bot, o[m]) if m > j else bot
                            return (0.5 * (swing / e - 1) + 0.5 * (x / e - 1) if half else x / e - 1), m - j + 1
                        if not half and m > j and h[m] >= swing:
                            half = True
                    xe = c[n - 1]
                    return (0.5 * (swing / e - 1) + 0.5 * (xe / e - 1) if half else xe / e - 1), n - j
            return None
    return None


def ema(x, n):
    k = 2 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def ema_cross(o, h, l, c):
    e9, e21 = ema(c, 9), ema(c, 21); n = len(c); res = []; i = 25
    while i < n - 2:
        if e9[i] > e21[i] and e9[i - 1] <= e21[i - 1]:
            e = o[i + 1]; sl = l[i - 9:i + 1].min(); R = e - sl
            if R <= 0:
                i += 1; continue
            be = False; x = None; j = i + 1; end = min(n - 1, i + 100)
            while j <= end:
                if l[j] <= sl:
                    x = min(sl, o[j]) if j > i + 1 else sl; break
                if not be and h[j] >= e + R:
                    be = True; sl = e
                if e9[j] < e21[j]:
                    x = c[j]; break
                j += 1
            if x is None:
                j = end; x = c[j]
            res.append((x / e - 1, j - i)); i = j
        i += 1
    return res


def real_ret(r, side):
    return r if side == 1 else 1 - 1 / (1 + r)


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
    period = {"5m": "60d", "15m": "60d", "1h": "730d"}[TF]

    def put(strat, side, r):
        if r is None or isinstance(r, str):
            return
        a = acc.setdefault((strat, side), [[], []]); a[0].append(real_ret(r[0], side) - cost); a[1].append(r[1])

    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period=period, interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = (d[s] if len(batch) > 1 else d).dropna(subset=["Close"])[["Open", "High", "Low", "Close"]].dropna()
                idx = df.index.tz_convert("Asia/Kolkata") if df.index.tz is not None else df.index
            except Exception:
                continue
            if len(df) < 120 or (df.to_numpy() <= 0).any():
                continue
            O, H, L, C = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            for side in (1, -1):
                o, h, l, c = (O, H, L, C) if side == 1 else (1 / O, 1 / L, 1 / H, 1 / C)
                if TF == "1h":
                    for r in ema_cross(o, h, l, c):
                        put("ema_cross", side, r)
                    continue
                days = np.array([t.date() for t in idx]); prev = None
                for dy in sorted(set(days)):
                    ii = np.where(days == dy)[0]
                    if len(ii) < 12:
                        continue
                    od, hd, ld, cd = o[ii], h[ii], l[ii], c[ii]
                    if TF == "5m":
                        put("silver_bullet", side, silver_bullet(od, hd, ld, cd, prev[0] if prev else None, prev[1] if prev else None) if prev else None)
                        if side == 1:
                            r = orb(od, hd, ld, cd)
                            put("orb", 1, r)
                            # short ORB = long ORB on the reciprocal series
                        else:
                            put("orb", -1, orb(od, hd, ld, cd))
                        put("fvg_fill", side, fvg_fill(od, hd, ld, cd))
                    else:
                        put("gap_fill", side, gap_fill(od, hd, ld, cd, prev[2] if prev else None))
                        put("ob_retest", side, ob_retest(od, hd, ld, cd))
                    prev = (hd.max(), ld.min(), cd[-1])
        print("batch", b0, flush=True)
    res = {}
    for (st, side), (rt, hl) in acc.items():
        r = np.array(rt)
        if len(r) < 30:
            print(st, side, "n", len(r), "too few"); continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        v, tf, pr = FAM[st]
        tag = f"{st}__{v}__{'long' if side == 1 else 'short'}__{tf}__{pr}__v1"
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
