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
UNI = os.environ.get("UNI") or "n200"
OUT = os.path.join(ROOT, "docs", "minervini_lab_results" + ("" if UNI == "n200" else "_full") + ".json")
MAXH = 60


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def clean_bars(df, max_move=0.35):
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    ok = (o <= h * 1.001) & (o >= l * 0.999) & (c <= h * 1.001) & (c >= l * 0.999) & (l > 0) & ((h / l) < 1.6)
    jump = (c / c.shift(1) - 1).abs() > max_move
    return df[ok & ~jump.fillna(False)]


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


def features(df, i, idx_close, rs_pct, nhnl_ok):
    """Boolean filters evaluated at signal bar i (uses only data up to i). B-213..B-273 batch."""
    c, h, l, v = (df[x].to_numpy(float) for x in ("Close", "High", "Low", "Volume"))
    f = {}
    pivot = h[i - 25:i].max()
    f["ext_le3"] = c[i] / pivot - 1 <= 0.03
    f["ext_le5"] = c[i] / pivot - 1 <= 0.05
    f["dryup"] = v[i - 6:i - 1].mean() < 0.5 * v[i - 55:i - 5].mean()
    rets = np.abs(c[i - 10:i] / c[i - 11:i - 1] - 1)
    f["tight_closes5"] = int((rets < 0.01).sum()) >= 5
    f["pivot_vol2x"] = v[i] >= 2 * v[i - 20:i].mean()
    f["stage2_30pct_off_low"] = c[i] >= 1.3 * l[i - 252:i].min()
    f["near_52w_high10"] = c[i] >= 0.9 * h[i - 252:i].max()
    f["base_depth_le25"] = (h[i - 60:i].max() - l[i - 60:i].min()) / h[i - 60:i].max() <= 0.25
    ma200 = pd.Series(c).rolling(200).mean().to_numpy()
    f["ma200_rising_100d"] = bool(ma200[i] > ma200[i - 100])
    up = c[i - 50:i] > c[i - 51:i - 1]
    f["updown_vol_pos"] = v[i - 50:i][up].sum() > v[i - 50:i][~up].sum()
    sdd = 1 - c[i] / c[i - 60:i].max()
    idd = 1 - idx_close[i] / idx_close[i - 60:i].max() if idx_close is not None else np.nan
    f["held_up_vs_index"] = bool(sdd <= 2 * idd + 0.02) if idx_close is not None else False
    if idx_close is not None:
        f["leaders_lead"] = bool(l[i - 20:i].min() > l[i - 40:i - 20].min() and idx_close[i - 20:i].min() < idx_close[i - 40:i - 20].min())
        off_low = idx_close[i] / idx_close[i - 120:i].min() - 1
        f["early_bull_10_25"] = bool(0.10 <= off_low <= 0.25)
        f["index_within5_of_high"] = bool(idx_close[i] >= 0.95 * idx_close[i - 252:i].max())
    f["rs_blend_ge70"] = bool(rs_pct is not None and rs_pct >= 70)
    f["breadth_nhnl_ok"] = bool(nhnl_ok)
    return f


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
    syms = [x for x in syms if x not in app.ETF_SYMBOLS]
    idx = yf.download("^NSEI", period="6y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(idx.columns, pd.MultiIndex):
        idx.columns = idx.columns.get_level_values(0)
    ic = idx["Close"].dropna()
    ic.index = pd.DatetimeIndex(ic.index).tz_localize(None)
    reg50 = (ic > ic.rolling(50).mean())
    reg200 = (ic > ic.rolling(200).mean())
    frames = {}
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
                df = clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= 300:
                df.index = pd.DatetimeIndex(df.index).tz_localize(None)
                frames[s] = df
        print("download", b0, len(frames), flush=True)
    closes = pd.DataFrame({s: f["Close"] for s, f in frames.items()})
    highs = pd.DataFrame({s: f["High"] for s, f in frames.items()})
    lows = pd.DataFrame({s: f["Low"] for s, f in frames.items()})
    blend = 0.4 * (closes / closes.shift(63) - 1) + 0.2 * (closes / closes.shift(126) - 1) + 0.2 * (closes / closes.shift(189) - 1) + 0.2 * (closes / closes.shift(252) - 1)
    rs_rank = blend.rank(axis=1, pct=True) * 100
    nh = (highs >= highs.rolling(252, min_periods=200).max()).sum(axis=1)
    nl = (lows <= lows.rolling(252, min_periods=200).min()).sum(axis=1)
    nhnl_ok = ((nh / (nh + nl).replace(0, np.nan)) >= 0.6).fillna(False)
    acc = {v: ([], []) for v in VARIANTS}
    facc = {}
    stream = []  # (entry date, ret) for the pct8_hard exit, for the stop-out-cluster rule
    nsig = 0
    for s, df in frames.items():
        sigs = collect_signals(df, app)
        base_sigs = [(i, float(df["Close"].iloc[i]), float(df["Close"].iloc[i]) * 0.9, 1.0) for i in range(210, len(df) - 2, 10)]
        dates = df.index
        for sg in base_sigs:
            for v in ("pct8_hard", "rr3", "ma200_break"):
                r = run_variant(v, df, sg, np.ones(len(df), bool), cost)
                if r:
                    acc.setdefault("baseline_" + v, ([], []))
                    acc["baseline_" + v][0].append(r[0])
                    acc["baseline_" + v][1].append(r[1])
        if not sigs:
            continue
        r50 = reg50.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
        r200 = reg200.reindex(dates, method="ffill").fillna(False).to_numpy(bool)
        idx_arr = ic.reindex(dates, method="ffill").to_numpy(float)
        rs_arr = rs_rank[s].reindex(dates).to_numpy(float)
        nn_arr = nhnl_ok.reindex(dates).fillna(False).to_numpy(bool)
        for sg in sigs:
            nsig += 1
            i = sg[0]
            for v in VARIANTS:
                ok = r50 if v == "regime_nifty50" else r200 if v == "regime_nifty200" else np.ones(len(df), bool)
                r = run_variant(v, df, sg, ok, cost)
                if r:
                    acc[v][0].append(r[0])
                    acc[v][1].append(r[1])
            try:
                ft = features(df, i, idx_arr, None if np.isnan(rs_arr[i]) else rs_arr[i], nn_arr[i])
            except Exception:
                ft = {}
            for ex in ("base", "pct8_hard"):
                r = run_variant(ex, df, sg, np.ones(len(df), bool), cost)
                if not r:
                    continue
                if ex == "pct8_hard":
                    stream.append((dates[i], r[0], r[1]))
                for name, val in ft.items():
                    k = (ex, name, "on" if val else "off")
                    facc.setdefault(k, ([], []))
                    facc[k][0].append(r[0])
                    facc[k][1].append(r[1])
        print("signals", nsig, flush=True)
    # B-259: stop-out cluster -> scale-down regime (>=3 losers among the previous 5 trades by entry date)
    stream.sort(key=lambda t: t[0])
    for j, (dte, r0, hd0) in enumerate(stream):
        prev = [x[1] for x in stream[max(0, j - 5):j]]
        flag = len(prev) == 5 and sum(1 for x in prev if x < 0) >= 3
        k = ("pct8_hard", "after_stopout_cluster", "on" if flag else "off")
        facc.setdefault(k, ([], []))
        facc[k][0].append(r0)
        facc[k][1].append(hd0)
    res = {}

    def put(tag, r, hd):
        if len(r) < 30:
            return
        r = np.array(r)
        g, lo = r[r > 0].sum(), -r[r < 0].sum()
        rs = np.sort(r)
        tr = rs[:-max(1, int(len(rs) * 0.01))]
        tl = -tr[tr < 0].sum()
        res[tag] = {"pfnet": round(float(g / lo), 3) if lo else None, "pfnet_trim1": round(float(tr[tr > 0].sum() / tl), 3) if tl else None,
                    "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)), "avg_net_pct": round(float(r.mean() * 100), 3),
                    "median_net_pct": round(float(np.median(r) * 100), 3), "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}

    for v, (r, hd) in acc.items():
        put(f"minervini_vcp__{v}__long__1d__h{MAXH}__v1", r, hd)
    for (ex, name, onoff), (r, hd) in facc.items():
        put(f"minervini_vcp__{ex}_f_{name}_{onoff}__long__1d__h{MAXH}__v1", r, hd)
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    for t, m in sorted(res.items(), key=lambda kv: -(kv[1]["pfnet"] or 0))[:40]:
        print(t, m["pfnet"], m["pfnet_trim1"], m["n"])


if __name__ == "__main__":
    main_run()
