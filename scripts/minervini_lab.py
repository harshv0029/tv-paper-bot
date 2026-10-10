"""Minervini exit/risk/regime variant lab (B-213..B-284 batch).

Entries come from the REAL main.minervini_vcp_entry_signal evaluated on every bar of each symbol's
history (RS gate skipped, as the original validation did). The same signal set is then replayed
under different exit / stop / regime rules, each variant its own tag
minervini_vcp__<variant>__long__1d__<params>__v1 (never pooled). Net of main.ROUND_TRIP_COST_PCT.
Env: UNI=n200 (default; the live swing watchlist) | full. Output docs/minervini_lab_results[_full].json
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UNI = os.environ.get("UNI", "n200")
OUT = os.path.join(ROOT, "docs", "minervini_lab_results" + ("" if UNI == "n200" else "_full") + ".json")
MAXH = 60


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def collect_signals(df, app):
    out = []
    c = df["Close"].to_numpy(float)
    ma50 = sma(c, 50)
    last = -10
    for i in range(210, len(df) - 2):
        if not (c[i] > ma50[i]) or i - last < 5:
            continue
        sub = df.iloc[: i + 1]
        try:
            sig = app.minervini_vcp_entry_signal(sub, None)
        except Exception:
            sig = None
        if sig:
            out.append((i, sig["entry_price"], sig["stop_loss"], sig["atr_at_entry"]))
            last = i
    return out


def run_variant(name, df, sig, regime_ok, cost):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    ma20, ma50, ma200 = sma(c, 20), sma(c, 50), sma(c, 200)
    i, entry, stop0, atr = sig
    n = len(c)
    if name.startswith("regime") and not regime_ok[i]:
        return None
    e = i + 1  # enter next open
    ent = o[e]
    if not ent or np.isnan(ent) or stop0 >= ent:
        return None
    stop = stop0
    peak = c[i]
    if name == "pct8_hard":
        stop = ent * 0.92
    elif name == "cap10_struct":
        stop = max(stop0, ent * 0.90)
    elif name == "cap15_struct":
        stop = max(stop0, ent * 0.85)
    R = ent - stop
    for j in range(e, min(e + MAXH, n)):
        if l[j] <= stop and j > e - 1:
            return (min(stop, o[j]) / ent - 1 - cost, j - e + 1)
        cj = c[j]
        held = j - e + 1
        peak = max(peak, cj)
        if name in ("base", "regime_nifty50", "cap10_struct", "cap15_struct", "regime_nifty200"):
            stop = max(stop, peak - 2.0 * atr)  # live chandelier
        if name == "ma20_fail" and held >= 3 and cj < ma20[j]:
            return (cj / ent - 1 - cost, held)
        if name == "ma50_trail" and cj < ma50[j]:
            return (cj / ent - 1 - cost, held)
        if name == "ma200_break" and cj < ma200[j]:
            return (cj / ent - 1 - cost, held)
        if name in ("rr2", "rr3"):
            tgt = ent + (2 if name == "rr2" else 3) * R
            if h[j] >= tgt:
                return (tgt / ent - 1 - cost, held)
        if name == "timestop10" and held == 10 and cj < ent * 1.02:
            return (cj / ent - 1 - cost, held)
        if name == "climax_sell":
            if cj / c[j - 1] - 1 >= 0.07 and cj > 1.25 * ma50[j]:
                return (cj / ent - 1 - cost, held)
        if name == "breakeven_after_1r" and cj >= ent + R:
            stop = max(stop, ent)
        if name == "gap_dn_exit" and o[j] < c[j - 1] * 0.95:
            return (o[j] / ent - 1 - cost, held)
    j = min(e + MAXH, n) - 1
    return (c[j] / ent - 1 - cost, j - e + 1)


VARIANTS = ("base", "pct8_hard", "cap10_struct", "cap15_struct", "ma20_fail", "ma50_trail", "ma200_break", "rr2", "rr3",
            "timestop10", "climax_sell", "breakeven_after_1r", "gap_dn_exit", "regime_nifty50", "regime_nifty200")


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = list(app.SWING_WATCHLIST) if UNI == "n200" else list(app._load_nse_universe_from_file())
    idx = yf.download("^NSEI", period="6y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(idx.columns, pd.MultiIndex):
        idx.columns = idx.columns.get_level_values(0)
    ic = idx["Close"].dropna()
    reg50 = (ic > ic.rolling(50).mean())
    reg200 = (ic > ic.rolling(200).mean())
    acc = {v: ([], []) for v in VARIANTS}
    nsig = 0
    for b0 in range(0, len(syms), 50):
        batch = syms[b0:b0 + 50]
        try:
            d = yf.download(batch, period="6y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            if len(df) < 300:
                continue
            sigs = collect_signals(df, app)
            if not sigs:
                continue
            dates = df.index.tz_localize(None) if df.index.tz is not None else df.index
            r50 = reg50.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
            r200 = reg200.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
            for sg in sigs:
                nsig += 1
                for v in VARIANTS:
                    ok = r50 if v == "regime_nifty50" else r200 if v == "regime_nifty200" else np.ones(len(df), bool)
                    r = run_variant(v, df, sg, ok, cost)
                    if r:
                        acc[v][0].append(r[0])
                        acc[v][1].append(r[1])
        print("batch", b0, "signals", nsig, flush=True)
    res = {}
    for v, (r, hd) in acc.items():
        if len(r) < 30:
            continue
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        res[f"minervini_vcp__{v}__long__1d__h{MAXH}__v1"] = {
            "pfnet": round(float(g / lo), 3) if lo else None, "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
            "avg_net_pct": round(float(r.mean() * 100), 3), "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda kv: -(kv[1]["pfnet"] or 0)):
        print(t, m)


if __name__ == "__main__":
    main_run()
