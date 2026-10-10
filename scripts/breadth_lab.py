"""Market-breadth indicators (B-163..B-173, B-176..B-178) as NIFTY timing signals, both directions.

Breadth is computed from the live swing universe (stocks of SWING_WATCHLIST, cleaned daily bars, 6y):
advances/declines, up/down volume, 52-week new highs/lows. Each rule yields a long and a short signal on ^NSEI.
Signal at close t -> NIFTY entry next open -> exit after H bars at the close (or ATR stop). Net of
main.ROUND_TRIP_COST_PCT. Every (rule, dir, hold, atr) is its own tag:
breadth__<rule>__<dir>__1d__atr<k>_h<H>__v1. Output docs/breadth_lab_results.json.
Midcap/smallcap ratio rules (B-176..B-178) use whichever of the candidate index tickers yfinance serves.
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
HOLDS = (3, 5, 10, 20)
KS = (0, 2.5)
OUT = os.path.join(ROOT, "docs", "breadth_lab_results.json")


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def clean(df):
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    ok = (o <= h * 1.001) & (o >= l * 0.999) & (c <= h * 1.001) & (c >= l * 0.999) & (l > 0) & ((h / l) < 1.6)
    return df[ok & ~((c / c.shift(1) - 1).abs() > 0.35).fillna(False)]


def cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def cross_dn(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


def build_breadth(closes, vols, highs, lows):
    adv = (closes.diff() > 0).sum(axis=1)
    dec = (closes.diff() < 0).sum(axis=1)
    unch = (closes.diff() == 0).sum(axis=1)
    upv = (vols.where(closes.diff() > 0)).sum(axis=1)
    dnv = (vols.where(closes.diff() < 0)).sum(axis=1)
    nh = (highs >= highs.rolling(252, min_periods=200).max()).sum(axis=1)
    nl = (lows <= lows.rolling(252, min_periods=200).min()).sum(axis=1)
    return adv, dec, unch, upv, dnv, nh, nl


def rules(idx_close, adv, dec, unch, upv, dnv, nh, nl, extra):
    out = {}
    net = adv - dec
    ad_line = net.cumsum()
    # AD line vs index divergence (B-163/B-164)
    idx_hi = idx_close >= idx_close.rolling(20).max()
    idx_lo = idx_close <= idx_close.rolling(20).min()
    ad_hi = ad_line >= ad_line.rolling(20).max()
    ad_lo = ad_line <= ad_line.rolling(20).min()
    out["ad_line_divergence"] = (idx_lo & ~ad_lo, idx_hi & ~ad_hi)  # bullish: index new low, AD not; bearish mirror
    out["ad_line_trend"] = (cross_up(ad_line, ad_line.rolling(50).mean()), cross_dn(ad_line, ad_line.rolling(50).mean()))
    # A/D ratio variants (B-165)
    r10 = (adv.rolling(10).sum() / (adv.rolling(10).sum() + dec.rolling(10).sum()))
    out["ad_ratio10_extreme"] = (cross_up(r10, pd.Series(0.40, index=r10.index)), cross_dn(r10, pd.Series(0.60, index=r10.index)))
    r_unch = adv / (adv + dec + unch).replace(0, np.nan)
    out["ad_ratio_with_unchanged"] = (cross_up(r_unch.rolling(10).mean(), pd.Series(0.35, index=r_unch.index)),
                                      cross_dn(r_unch.rolling(10).mean(), pd.Series(0.55, index=r_unch.index)))
    # McClellan oscillator / summation (B-166/B-167)
    ratio_adj = (net / (adv + dec).replace(0, np.nan)) * 1000
    mco = ema(ratio_adj, 19) - ema(ratio_adj, 39)
    zero = pd.Series(0.0, index=mco.index)
    out["mcclellan_zero_cross"] = (cross_up(mco, zero), cross_dn(mco, zero))
    out["mcclellan_extreme_reversal"] = (cross_up(mco, pd.Series(-100.0, index=mco.index)), cross_dn(mco, pd.Series(100.0, index=mco.index)))
    summ = mco.cumsum()
    out["mcclellan_summation_zero"] = (cross_up(summ, summ.rolling(50).mean()), cross_dn(summ, summ.rolling(50).mean()))
    # New highs/new lows (B-168/B-169)
    nhnl = (nh - nl).rolling(10).mean()
    out["nh_nl_10d_zero"] = (cross_up(nhnl, zero), cross_dn(nhnl, zero))
    out["nh_nl_divergence"] = (idx_lo & (nhnl > nhnl.shift(20)), idx_hi & (nhnl < nhnl.shift(20)))
    # Up/down volume (B-170)
    udv = (upv.rolling(10).sum() / dnv.rolling(10).sum().replace(0, np.nan))
    out["updown_volume_10d"] = (cross_up(udv, pd.Series(1.0, index=udv.index)), cross_dn(udv, pd.Series(1.0, index=udv.index)))
    out["updown_volume_extreme"] = (udv < 0.6, udv > 1.8)  # contrarian washout / blow-off
    # Arms index TRIN (B-171..B-173)
    trin = (adv / dec.replace(0, np.nan)) / (upv / dnv.replace(0, np.nan))
    t10 = trin.rolling(10).mean()
    out["trin_10d_contrarian"] = (cross_up(t10, pd.Series(1.20, index=t10.index)).shift(0) | (t10 > 1.20) & (t10.shift(1) <= 1.20),
                                  (t10 < 0.70) & (t10.shift(1) >= 0.70))
    t21, t55 = trin.rolling(21).mean(), trin.rolling(55).mean()
    out["trin_21_55_cross"] = (cross_dn(t21, t55), cross_up(t21, t55))  # falling TRIN is bullish
    open_arms = (adv.rolling(10).mean() / dec.rolling(10).mean().replace(0, np.nan)) / (upv.rolling(10).mean() / dnv.rolling(10).mean().replace(0, np.nan))
    out["open_arms_contrarian"] = ((open_arms > 1.20) & (open_arms.shift(1) <= 1.20), (open_arms < 0.70) & (open_arms.shift(1) >= 0.70))
    # Dow-style / ratio rules from extra index series (B-176..B-178)
    for name, ser in extra.items():
        ser = ser.reindex(idx_close.index).ffill()
        ratio = ser / idx_close
        out[f"ratio_{name}_trend"] = (cross_up(ratio, ratio.rolling(50).mean()), cross_dn(ratio, ratio.rolling(50).mean()))
        both_hi = (ser >= ser.rolling(60).max()) & (idx_close >= idx_close.rolling(60).max())
        both_lo = (ser <= ser.rolling(60).min()) & (idx_close <= idx_close.rolling(60).min())
        out[f"dow_confirm_{name}"] = (both_hi & ~both_hi.shift(1).fillna(False), both_lo & ~both_lo.shift(1).fillna(False))
    return out


def simulate(sig, o, h, l, c, atr, hold, k, cost, side):
    rets, held = [], []
    n = len(c)
    nxt = 0
    for t in np.flatnonzero(sig):
        if t < nxt or t + 1 >= n or np.isnan(atr[t]):
            continue
        e = t + 1
        last = e + hold - 1
        if last >= n:
            continue
        ent = o[e]
        stop = ent - side * k * atr[t]
        exitp, j_exit = c[last], last
        if k:
            for j in range(e, last + 1):
                if side == 1 and l[j] <= stop:
                    exitp, j_exit = min(stop, o[j]), j
                    break
                if side == -1 and h[j] >= stop:
                    exitp, j_exit = max(stop, o[j]), j
                    break
        rets.append((exitp / ent - 1) * side - cost)
        held.append(j_exit - e + 1)
        nxt = j_exit + 1
    return rets, held


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = sorted(set(app.SWING_WATCHLIST) - set(app.ETF_SYMBOLS))
    cl, vo, hi, lo = {}, {}, {}, {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period="6y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as ex:
            print("batch fail", ex)
            continue
        for s in batch:
            try:
                df = clean(d[s].dropna(subset=["Close"])[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) < 300:
                continue
            cl[s], vo[s], hi[s], lo[s] = df["Close"], df["Volume"], df["High"], df["Low"]
        print("breadth batch", b0, len(cl), flush=True)
    closes, vols, highs, lows = (pd.DataFrame(x) for x in (cl, vo, hi, lo))
    for f in (closes, vols, highs, lows):
        f.index = pd.DatetimeIndex(f.index).tz_localize(None)
    adv, dec, unch, upv, dnv, nh, nl = build_breadth(closes, vols, highs, lows)
    idx = yf.download("^NSEI", period="6y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(idx.columns, pd.MultiIndex):
        idx.columns = idx.columns.get_level_values(0)
    idx = clean(idx.dropna(subset=["Close"])[["Open", "High", "Low", "Close"]].dropna())
    idx.index = pd.DatetimeIndex(idx.index).tz_localize(None)
    extra = {}
    for name, tk in (("midcap", "^NSEMDCP50"), ("bank", "^NSEBANK"), ("junior", "^NSMIDCP")):
        try:
            e = yf.download(tk, period="6y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(e.columns, pd.MultiIndex):
                e.columns = e.columns.get_level_values(0)
            if len(e.dropna(subset=["Close"])) > 500:
                s = e["Close"].dropna()
                s.index = pd.DatetimeIndex(s.index).tz_localize(None)
                extra[name] = s
        except Exception as ex:
            print("extra fail", tk, ex)
    ic = idx["Close"]
    ix = idx.index
    sigs = rules(ic, *(x.reindex(ix).ffill() for x in (adv, dec, unch, upv, dnv, nh, nl)), extra)
    o, h, l, c = (idx[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    pc = np.roll(c, 1)
    atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
    res = {}
    for rule, (lg, sh) in sigs.items():
        for dname, sg, side in (("long", lg, 1), ("short", sh, -1)):
            sg = np.asarray(sg.reindex(ix).fillna(False), bool)
            if sg.sum() < 5:
                continue
            for H in HOLDS:
                for k in KS:
                    r, hd = simulate(sg, o, h, l, c, atr, H, k, cost, side)
                    if len(r) < 20:
                        continue
                    r = np.array(r)
                    g, lo_ = r[r > 0].sum(), -r[r < 0].sum()
                    ks = "none" if not k else str(k).replace(".", "d")
                    res[f"breadth__{rule}__{dname}__1d__atr{ks}_h{H}__v1"] = {
                        "pfnet": round(float(g / lo_), 3) if lo_ else None, "win_pct": round(float((r > 0).mean() * 100), 1),
                        "n": int(len(r)), "avg_net_pct": round(float(r.mean() * 100), 3), "median_net_pct": round(float(np.median(r) * 100), 3),
                        "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}
    # baseline: every bar long/short on the index
    allb = np.ones(len(c), bool)
    for dname, side in (("long", 1), ("short", -1)):
        for H in HOLDS:
            r, hd = simulate(allb, o, h, l, c, atr, H, 0, cost, side)
            if len(r) >= 20:
                r = np.array(r)
                g, lo_ = r[r > 0].sum(), -r[r < 0].sum()
                res[f"breadth__baseline_every_bar__{dname}__1d__atrnone_h{H}__v1"] = {
                    "pfnet": round(float(g / lo_), 3) if lo_ else None, "win_pct": round(float((r > 0).mean() * 100), 1), "n": int(len(r)),
                    "avg_net_pct": round(float(r.mean() * 100), 3), "median_net_pct": round(float(np.median(r) * 100), 3),
                    "avg_held_bars": round(float(np.mean(hd)), 2), "bar_hours": 6.25}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    print("cells", len(res), "extra indexes", list(extra))
    for t, m in sorted(res.items(), key=lambda kv: -(kv[1]["pfnet"] or 0))[:25]:
        print(t, m)


if __name__ == "__main__":
    main_run()
