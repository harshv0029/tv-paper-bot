"""RSI(10) pullback above SMA200 (daily), both directions. Long: close>SMA200, RSI10<en -> buy next open; exit when RSI10>ex
(next open), hard stop below swing low (sw-bar low), time stop hd bars. Short mirror: close<SMA200, RSI10>100-en, exit RSI10<100-ex,
stop above swing high. Sweep en (30,20), ex (40,50), sw (5,10). Env: UNI (n200|etf|blank=full), MAXSYM.
Out: docs/rsi_pullback_sma200_results[_uni].json. Tags: rsi_pullback__sma200__<dir>__1d__en30_ex40_hd10_sw10__v1"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
UNI = os.environ.get("UNI", "")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "rsi_pullback_sma200_results" + (f"_{UNI}" if UNI in ("n200", "etf") else "") + ".json")
HD = 10
GRID = [(en, ex, sw) for en in (30, 20) for ex in (40, 50) for sw in (5, 10)]


def rsi(c, n=10):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    au, ad = up[1:n + 1].mean(), dn[1:n + 1].mean()
    out[n] = 100 - 100 / (1 + au / ad) if ad else 100.0
    for i in range(n + 1, len(c)):
        au = (au * (n - 1) + up[i]) / n; ad = (ad * (n - 1) + dn[i]) / n
        out[i] = 100 - 100 / (1 + au / ad) if ad else 100.0
    return out


def sma(c, n):
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        cs = np.cumsum(np.r_[0, c]); out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def trades(o, h, l, c, r, m, side, en, ex, sw, cost):
    rets, held = [], []; n = len(c); i = 200
    while i < n - 2:
        sig = (c[i] > m[i] and r[i] < en) if side == 1 else (c[i] < m[i] and r[i] > 100 - en)
        if not sig or np.isnan(r[i]) or np.isnan(m[i]):
            i += 1; continue
        e = o[i + 1]
        sl = l[max(0, i - sw + 1):i + 1].min() if side == 1 else h[max(0, i - sw + 1):i + 1].max()
        if e <= 0 or (side == 1 and e <= sl) or (side == -1 and e >= sl):
            i += 1; continue
        x = None; j = i + 1; end = min(n, i + 1 + HD)
        while j < end:
            if side == 1 and l[j] <= sl:
                x = min(sl, o[j]); break
            if side == -1 and h[j] >= sl:
                x = max(sl, o[j]); break
            if j > i + 1 and ((side == 1 and r[j - 1] > ex) or (side == -1 and r[j - 1] < 100 - ex)):
                x = o[j]; break
            j += 1
        if x is None:
            j = end - 1; x = c[j] if end - 1 == n - 1 else o[end] if end < n else c[j]
        ret = (x / e - 1) if side == 1 else (1 - x / e)
        if abs(ret) < 0.4:
            rets.append(ret - cost); held.append(j - i)
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
            d = yf.download(batch, period="5y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True); continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close"]].dropna()
            except Exception:
                continue
            if len(df) < 260:
                continue
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            if (c <= 0).any() or (o <= 0).any():
                continue
            r = rsi(c); m = sma(c, 200)
            for side, nm in ((1, "long"), (-1, "short")):
                for en, ex, sw in GRID:
                    rt, hl = trades(o, h, l, c, r, m, side, en, ex, sw, cost)
                    a = acc.setdefault((nm, en, ex, sw), [[], []]); a[0] += rt; a[1] += hl
        print("batch", b0, flush=True)
    res = {}
    for (nm, en, ex, sw), (rt, hl) in acc.items():
        r = np.array(rt)
        if len(r) < 30:
            continue
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r); cut = max(1, int(len(rs) * 0.01)); tr = rs[:-cut]; tl = -tr[tr < 0].sum()
        tag = f"rsi_pullback__sma200__{nm}__1d__en{en}_ex{ex}_hd{HD}_sw{sw}__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None,
                    "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 4), "median_net_pct": round(float(np.median(r) * 100), 4),
                    "avg_held_bars": round(float(np.mean(hl)), 2), "bar_hours": 6.25}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m_ in sorted(res.items(), key=lambda x: -(x[1]["pfnet"] or 0)):
        print(t, m_["pfnet"], m_["pfnet_trim1"], m_["win_pct"], m_["n"], m_["avg_net_pct"])


if __name__ == "__main__":
    main_run()
