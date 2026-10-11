"""Ernest Chan extension research (backlog B-431, B-439, B-441, B-442, B-447, B-448, B-449, B-450, B-451, B-457, B-458).

Complements scripts/chan_research.py (which covers gap, tsm, alexander, shape, ema regime, updays, z-score MR,
xs open-to-close). Same conventions: FULL NSE universe (main._load_nse_universe_from_file()), BOTH directions as
separate tags, ATR stop on EVERY trade (k 1.5/2.5/4.0), 0.8% round-trip cost, naming grammar
<family>__<variant>__<dir>__<tf>__<params>__v1, mergeable additive cells (orx.acc_add / merge_cells / finalize).
Reuses chan_research.simulate/atr_arr/half_life (never a reimplementation of the trade loop).

Families (per interval; INTERVAL in 1d|1h|15m|5m, yfinance period 5y|730d|60d|60d):
  chan_xsmom__decile252     B-431  252d-return decile, long top / short bottom, 25-bar hold, liquidity filter (1d)
                            B-451  momentum-crash gate: skip rebalances when NIFTY 60d drawdown < -5% / -10% (cr05, cr10)
  chan_kalman__band         B-441  Kalman adaptive mean on log price (delta 1e-4, Ve 1e-4|1e-3), band z 1|2, exit at mean
  chan_vwma__band           B-442  bar-volume-weighted anchor (L 20|50, z 1.5|2.5); intraday intervals force EOD flat
  chan_lateday__continuation B-439 return prior close->15:00 IST beyond 1|2|3% continues to the close (5m/15m only);
                            index-futures path owed (no futures history in this harness)
  chan_mrgate__fixed20      B-447/B-448 z20 mean reversion gated by a stationarity battery (adf, hurst, vr, hl, all)
                            and by a rolling ADF-break monitor (adfbreak, forced exit when stationarity breaks)
  chan_vixgate__*           B-450  every chan_research-style ts family re-run under India VIX gates (1d only)
  year split                B-457  every ts cell at k=2.5 also emitted per entry year (y<year>) so a recent-window
                            (survivorship-light) result is read directly; delisted-inclusive data is NOT available (owed)
  corr scan                 B-449  sign-correlation of past-lb return vs next-hold return, non-overlapping samples
  hygiene                   B-458  bad-tick/jump/zero-volume/duplicate-index counts per universe (HYGIENE=1)
Env: INTERVAL, SHARD, NSHARDS, MAXSYM, HYGIENE. Output docs/chan_ext_<interval>_s<shard>.json; `--merge files...`.
"""
import json
import math
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import chan_research as chn  # noqa: E402
import oneil_research as orx  # noqa: E402

KS = chn.KS
PERIOD = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}
INTRADAY = ("5m", "15m")
LIQ_MIN_TURNOVER = 2e7
REB_HOLD = 25
VIX_GATES = (("none", None), ("le20", (0, 20)), ("le25", (0, 25)), ("le35", (0, 35)), ("ge20", (20, 999)))
CORR_LB = (5, 20, 60)
CORR_HOLD = (1, 5, 25)


def kf(x):
    return chn.kfmt(x)


def tag(fam, var, d, tf, params):
    return chn.tag(fam, var, d, tf, params)


# ---------------------------------------------------------------- indicators
def kalman_band(y, delta=1e-4, ve=1e-3):
    """1-D Kalman filter on log price (state = adaptive mean). Returns (err, sqrtQ) per bar, err = y - mean forecast."""
    n = len(y)
    vw = delta / (1 - delta)
    beta, P = y[0], 1.0
    err, sq = np.full(n, np.nan), np.full(n, np.nan)
    for t in range(n):
        R = P + vw
        Q = R + ve
        e = y[t] - beta
        err[t], sq[t] = e, math.sqrt(Q)
        K = R / Q
        beta += K * e
        P = R - K * R
    return err, sq


def adf_t(y):
    """Dickey-Fuller t-stat (lag 0, constant): dy = a + g*y[t-1]. Critical (n~100): -2.871 at 5%."""
    y = np.asarray(y, float)
    dy, yl = np.diff(y), y[:-1]
    x = yl - yl.mean()
    sxx = (x * x).sum()
    if len(dy) < 10 or sxx <= 0:
        return np.nan
    g = (x * (dy - dy.mean())).sum() / sxx
    resid = dy - dy.mean() - g * x
    s2 = (resid ** 2).sum() / (len(dy) - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else np.nan
    return g / se if se and se > 0 else np.nan


def hurst(y):
    y = np.asarray(y, float)
    lags = np.arange(2, min(20, len(y) // 4))
    if len(lags) < 3:
        return np.nan
    sd = [np.std(y[l:] - y[:-l]) for l in lags]
    if min(sd) <= 0:
        return np.nan
    return float(np.polyfit(np.log(lags), np.log(sd), 1)[0])


def var_ratio(y, q=5):
    y = np.asarray(y, float)
    d1 = np.diff(y)
    dq = y[q:] - y[:-q]
    v1 = np.var(d1)
    return float(np.var(dq) / (q * v1)) if v1 > 0 else np.nan


def stationarity_gates(c, W=120, step=10):
    """Per-bar boolean gates + rolling ADF t, forward-filled from every `step` bars (no look-ahead)."""
    n = len(c)
    y = np.log(c)
    keys = ("adf", "hurst", "vr", "hl")
    g = {k: np.zeros(n, bool) for k in keys}
    tstat = np.full(n, np.nan)
    cur = None
    for i in range(W, n):
        if cur is None or i % step == 0:
            w = y[i - W:i + 1]
            lam, hl = chn.half_life(w)
            cur = (adf_t(w), hurst(w), var_ratio(w), lam, hl)
        t, H, vr, lam, hl = cur
        tstat[i] = t
        g["adf"][i] = (not np.isnan(t)) and t < -2.871
        g["hurst"][i] = (not np.isnan(H)) and H < 0.5
        g["vr"][i] = (not np.isnan(vr)) and vr < 1.0
        g["hl"][i] = lam < 0 and hl <= 30
    return g, tstat


def day_flags(df):
    """Last-bar-of-day flag for intraday forced flat. Index tz-aware or naive."""
    d = pd.Series(df.index.date, index=df.index)
    return (d != d.shift(-1)).to_numpy()


def intraday_wrap(sig, xl, xs, last):
    sig = sig.copy()
    sig[last] = 0
    xl = (xl if xl is not None else np.zeros(len(sig), bool)) | last
    xs = (xs if xs is not None else np.zeros(len(sig), bool)) | last
    return sig, xl, xs


# ---------------------------------------------------------------- cell generators
def mr_gate_cells(c, interval):
    """B-447/B-448: fixed z20 mean reversion, gated by the stationarity battery."""
    n = len(c)
    z = chn.zscores(c, (20,))[20]
    base_l, base_s = z < -1, z > 1
    gates, tstat = stationarity_gates(c)
    allg = gates["adf"] & gates["hurst"] & gates["vr"] & gates["hl"]
    t_prev = np.r_[np.full(20, np.nan), tstat[:-20]] if n > 20 else np.full(n, np.nan)
    with np.errstate(invalid="ignore"):
        brk_ok = (tstat < -1.95) & ~(tstat - t_prev > 1.0)
    brk_ok = np.nan_to_num(brk_ok.astype(float)).astype(bool)
    variants = {"none": np.ones(n, bool), "adf": gates["adf"], "hurst": gates["hurst"], "vr": gates["vr"],
                "hl": gates["hl"], "all": allg, "adfbreak": brk_ok}
    ok = ~np.isnan(z)
    for name, gate in variants.items():
        s = np.zeros(n)
        s[ok & gate & base_l], s[ok & gate & base_s] = 1, -1
        xl = (z >= 0)
        xs = (z <= 0)
        if name == "adfbreak":  # regime stop: leave when stationarity evidence degrades
            xl, xs = xl | ~brk_ok, xs | ~brk_ok
        yield "chan_mrgate", "fixed20", {"gate": name, "hold": 40}, s, 40, xl, xs


def kalman_cells(c, interval):
    y = np.log(c)
    for ve in (1e-4, 1e-3):
        err, sq = kalman_band(y, 1e-4, ve)
        for zth in (1.0, 2.0):
            s = np.zeros(len(c))
            s[err < -zth * sq], s[err > zth * sq] = 1, -1
            yield "chan_kalman", "band", {"hold": 40, "ve": kf(ve * 1e4) + "e4", "z": kf(zth)}, s, 40, err >= 0, err <= 0


def vwma_cells(c, v, interval):
    cs = pd.Series(c)
    for L in (20, 50):
        pv = (cs * pd.Series(v)).rolling(L).sum() / pd.Series(v).rolling(L).sum()
        sd = cs.rolling(L).std()
        z = ((cs - pv) / sd).to_numpy()
        for zth in (1.5, 2.5):
            s = np.zeros(len(c))
            s[z < -zth], s[z > zth] = 1, -1
            yield "chan_vwma", "band", {"hold": L, "lk": L, "z": kf(zth)}, s, L, z >= 0, z <= 0


def base_ts_cells(o, h, l, c, atr, interval):
    return chn.ts_cells(o, h, l, c, atr, interval)


def vix_masks(dates, vix):
    out = {}
    v = vix.reindex(dates).ffill().to_numpy(float) if vix is not None else None
    for name, rng_ in VIX_GATES:
        if rng_ is None:
            out[name] = np.ones(len(dates), bool)
        elif v is not None:
            out[name] = (v >= rng_[0]) & (v <= rng_[1])
    return out


def lateday_trades(df, k_list, cost, interval, thr_list=(0.01, 0.02, 0.03)):
    """B-439: prior close -> 15:00 IST return beyond thr continues to the close. Returns {tag: rows}."""
    out = {}
    idx = df.index
    try:
        local = idx.tz_convert("Asia/Kolkata") if idx.tz is not None else idx
    except Exception:
        local = idx
    days = pd.Series(local.date, index=range(len(df)))
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    tmin = np.array([t.hour * 60 + t.minute for t in local])
    atr = chn.atr_arr(h, l, c)
    prev_close = None
    for day, g in days.groupby(days):
        ii = g.index.to_numpy()
        entry = [i for i in ii if tmin[i] >= 15 * 60]
        pre = [i for i in ii if tmin[i] < 15 * 60]
        if prev_close is None or not entry or not pre:
            prev_close = c[ii[-1]]
            continue
        e = entry[0]
        ret = c[pre[-1]] / prev_close - 1
        A = atr[pre[-1]]
        for thr in thr_list:
            side = 1 if ret >= thr else (-1 if ret <= -thr else 0)
            if side == 0 or not A or np.isnan(A) or A <= 0:
                continue
            for k in k_list:
                ep = o[e]
                stop = ep - side * k * A
                xp, why = c[ii[-1]], "close"
                for j in range(e, ii[-1] + 1):
                    if side == 1 and l[j] <= stop:
                        xp, why = (min(stop, o[j]) if j > e else stop), "stop"
                        break
                    if side == -1 and h[j] >= stop:
                        xp, why = (max(stop, o[j]) if j > e else stop), "stop"
                        break
                g_ = (xp / ep - 1) * side
                nm = "long" if side == 1 else "short"
                t = tag("chan_lateday", "continuation", nm, interval, {"atr": kf(k), "ret": kf(thr * 100)})
                out.setdefault(t, []).append((g_ - cost, g_, int(ii[-1] - e + 1), why))
        prev_close = c[ii[-1]]
    return out


# ---------------------------------------------------------------- run
def sim_to_rows(tr, side, cost):
    sub = [t for t in tr if t[0] == side]
    return [(t[3] - cost, t[3], t[2] - t[1] + 1, t[4]) for t in sub], sub


def download(batch, interval):
    import yfinance as yf
    return yf.download(batch, period=PERIOD[interval], interval=interval, group_by="ticker", auto_adjust=True,
                       progress=False, threads=True)


def _series(sym):
    import yfinance as yf
    try:
        d = yf.download(sym, period="5y", interval="1d", auto_adjust=True, progress=False)
        col = d["Close"]
        return (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna()
    except Exception as e:
        print("download failed", sym, e, flush=True)
        return None


def hygiene_row(df):
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
    bad_ohlc = int(((o > h * 1.001) | (o < l * 0.999) | (c > h * 1.001) | (c < l * 0.999) | (l <= 0)).sum())
    jumps = int((np.abs(c[1:] / c[:-1] - 1) > 0.35).sum())
    return dict(bars=int(len(df)), bad_ohlc=bad_ohlc, jump_gt35=jumps, zero_vol=int((v <= 0).sum()),
                dup_index=int(df.index.duplicated().sum()), max_abs_ret=float(np.nanmax(np.abs(c[1:] / c[:-1] - 1))) if len(c) > 1 else 0.0)


def run():
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    interval = os.environ.get("INTERVAL", "1d")
    shard, nsh = int(os.environ.get("SHARD", 0)), int(os.environ.get("NSHARDS", 1))
    syms = sorted(app._load_nse_universe_from_file())
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    syms = syms[shard::nsh]
    hyg_only = os.environ.get("HYGIENE") == "1"
    vix = _series("^INDIAVIX") if (interval == "1d" and not hyg_only) else None
    nifty = _series("^NSEI") if (interval == "1d" and not hyg_only) else None
    idd = None
    if nifty is not None:
        idd = nifty / nifty.rolling(60, min_periods=1).max() - 1
    cells, xs_rows, corr, hyg = {}, [], {}, {}
    kept = 0

    def add(t, rows):
        if rows:
            orx.acc_add(cells, t, rows)

    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = download(batch, interval)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s] if len(batch) > 1 else d
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            if len(df) < 160:
                continue
            if hyg_only:
                hyg[s] = hygiene_row(df)
                continue
            o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
            if (o <= 0).any() or (np.abs(c[1:] / c[:-1] - 1) > 0.4).any():  # bad-tick / split guard (B-458)
                continue
            kept += 1
            atr = chn.atr_arr(h, l, c)
            last = day_flags(df) if interval in INTRADAY else None
            gens = [kalman_cells(c, interval), vwma_cells(c, v, interval)]
            if interval in ("1d", "1h"):
                gens.append(mr_gate_cells(c, interval))
            for gen in gens:
                for fam, var, params, sig, hold, xl, xsx in gen:
                    if last is not None:
                        sig, xl, xsx = intraday_wrap(sig, xl, xsx, last)
                    for k in KS:
                        tr = chn.simulate(o, h, l, c, atr, sig, k, hold, xl, xsx)
                        for side, nm in ((1, "long"), (-1, "short")):
                            rows, _ = sim_to_rows(tr, side, cost)
                            add(tag(fam, var, nm, interval, {**params, "atr": kf(k)}), rows)
            if interval == "1d":
                dates = df.index.tz_localize(None) if df.index.tz is not None else df.index
                dstr = dates.strftime("%Y%m%d").to_numpy()
                vm = vix_masks(dates, vix)
                for fam, var, params, sig, hold, xl, xsx in base_ts_cells(o, h, l, c, atr, interval):
                    # B-450 VIX gates (k=2.5 only, to bound cost) and B-457 per-year split (k=2.5)
                    k = 2.5
                    for gname, mask in vm.items():
                        if gname == "none":
                            continue
                        s2 = np.where(mask, sig, 0)
                        tr = chn.simulate(o, h, l, c, atr, s2, k, hold, xl, xsx)
                        for side, nm in ((1, "long"), (-1, "short")):
                            rows, _ = sim_to_rows(tr, side, cost)
                            add(tag(fam, var, nm, interval, {**params, "atr": kf(k), "vix": gname}), rows)
                    tr = chn.simulate(o, h, l, c, atr, sig, k, hold, xl, xsx)
                    for side, nm in ((1, "long"), (-1, "short")):
                        _, sub = sim_to_rows(tr, side, cost)
                        by = {}
                        for t in sub:
                            by.setdefault(int(dstr[t[1]][:4]), []).append((t[3] - cost, t[3], t[2] - t[1] + 1, t[4]))
                        for yr, rows in by.items():
                            add(tag(fam, var, nm, interval, {**params, "atr": kf(k), "y": yr}), rows)
                # B-431 / B-451 cross-sectional momentum rebalance rows
                turn = pd.Series(c * v).rolling(20).median().to_numpy()
                wk = pd.Series(dates.isocalendar().week.to_numpy(), index=range(len(dates)))
                first_of_week = (wk != wk.shift(1)).to_numpy()
                for i in range(252, len(c) - REB_HOLD - 2):
                    if not (first_of_week[i] and wk.iloc[i] % 5 == 0) or turn[i] < LIQ_MIN_TURNOVER or atr[i] <= 0 or np.isnan(atr[i]):
                        continue
                    ret252 = c[i] / c[i - 252] - 1
                    g = {}
                    for k in KS:
                        tr = chn.simulate(o, h, l, c, atr, np.where(np.arange(len(c)) == i, 1, 0), k, REB_HOLD)
                        trs = chn.simulate(o, h, l, c, atr, np.where(np.arange(len(c)) == i, -1, 0), k, REB_HOLD)
                        g[kf(k)] = [tr[0][3] if tr else None, trs[0][3] if trs else None,
                                    (tr[0][2] - tr[0][1] + 1) if tr else None, tr[0][4] if tr else None, trs[0][4] if trs else None]
                    dd = float(idd.reindex([dates[i]], method="ffill").iloc[0]) if idd is not None else 0.0
                    xs_rows.append([dstr[i], float(ret252), dd, g])
                # B-449 correlation scan (non-overlapping samples)
                for lb in CORR_LB:
                    for H in CORR_HOLD:
                        step = max(lb, H)
                        idxs = np.arange(lb, len(c) - H, step)
                        x = np.sign(c[idxs] / c[idxs - lb] - 1)
                        y = c[idxs + H] / c[idxs] - 1
                        a = corr.setdefault(f"lb{lb}_h{H}", [0, 0.0, 0.0, 0.0, 0.0, 0.0])
                        a[0] += len(x)
                        a[1] += float(x.sum()); a[2] += float(y.sum()); a[3] += float((x * y).sum())
                        a[4] += float((x * x).sum()); a[5] += float((y * y).sum())
            if interval in INTRADAY:
                for t, rows in lateday_trades(df, KS, cost, interval).items():
                    add(t, rows)
        print("batch", b0, "cells", len(cells), "kept", kept, flush=True)
    out_dir = os.environ.get("OUT_DIR", os.path.join(ROOT, "docs"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chan_ext_{'hyg_' if hyg_only else ''}{interval}_s{shard}.json")
    with open(path, "w") as f:
        json.dump({"interval": interval, "shard": shard, "universe_requested": len(syms), "symbols": kept,
                   "cells": cells, "xs": xs_rows, "corr": corr, "hygiene": hyg},
                  f, default=lambda o_: o_.item() if hasattr(o_, "item") else str(o_))
    print("wrote", path)


# ---------------------------------------------------------------- merge
def xs_cells(rows, cost, min_names=200):
    """Per rebalance date: rank 252d return, long top decile / short bottom decile. Crash gates by NIFTY 60d drawdown."""
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    cells = {}
    gates = (("none", None), ("cr05", -0.05), ("cr10", -0.10))
    for dt, rs in by.items():
        if len(rs) < min_names:
            continue
        rs = sorted(rs, key=lambda r: r[1])
        m = max(1, len(rs) // 10)
        bottom, top = rs[:m], rs[-m:]
        for gname, thr in gates:
            for sel, side, nm in ((top, 0, "long"), (bottom, 1, "short")):
                for r in sel:
                    if thr is not None and r[2] < thr:
                        continue
                    for k, vals in r[3].items():
                        gv = vals[side]
                        if gv is None:
                            continue
                        t = tag("chan_xsmom", "decile252", nm, "1d", {"atr": k, "hold": REB_HOLD, "crash": gname})
                        orx.acc_add(cells, t, [(gv - cost, gv, REB_HOLD, "stop_or_hold")])
    return cells


def merge(paths):
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    parts = [json.load(open(p)) for p in paths]
    cells = orx.merge_cells([p["cells"] for p in parts if p.get("cells")])
    rows = [r for p in parts for r in p.get("xs", [])]
    if rows:
        for t, c in xs_cells(rows, cost).items():
            cells[t] = c
    res = orx.finalize(cells, min_n=30)
    uni = sum(p.get("symbols", 0) for p in parts)
    req = sum(p.get("universe_requested", 0) for p in parts)
    corr = {}
    for p in parts:
        for k, a in p.get("corr", {}).items():
            t = corr.setdefault(k, [0, 0.0, 0.0, 0.0, 0.0, 0.0])
            for i in range(6):
                t[i] += a[i]
    corr_out = {}
    for k, (n, sx, sy, sxy, sxx, syy) in corr.items():
        if n > 30:
            cov = sxy / n - (sx / n) * (sy / n)
            vx, vy = sxx / n - (sx / n) ** 2, syy / n - (sy / n) ** 2
            corr_out[k] = dict(n=int(n), corr=round(cov / math.sqrt(vx * vy), 4) if vx > 0 and vy > 0 else None)
    hyg = {}
    for p in parts:
        hyg.update(p.get("hygiene", {}))
    hy_sum = None
    if hyg:
        hy_sum = {k: int(sum(h[k] for h in hyg.values())) for k in ("bars", "bad_ohlc", "jump_gt35", "zero_vol", "dup_index")}
        hy_sum["symbols"] = len(hyg)
        hy_sum["symbols_with_jump"] = sum(1 for h in hyg.values() if h["jump_gt35"])
    out = os.environ.get("OUT", os.path.join(ROOT, "docs", "chan_ext_results.json"))
    json.dump({"cost_round_trip": cost, "universe_symbols": uni, "universe_requested": req,
               "owed": ["delisted-inclusive universe (B-457)", "index-futures path for B-439", "4h resample", "B-456 MIS-shortable list"],
               "corr_scan": corr_out, "hygiene": hy_sum, "results": res}, open(out, "w"), indent=0,
              default=lambda o_: o_.item() if hasattr(o_, "item") else str(o_))
    print(f"universe_symbols={uni}/{req} cells={len(res)}")
    if hy_sum:
        print("HYGIENE", json.dumps(hy_sum))
    for k, v in sorted(corr_out.items()):
        print("CORR", k, v)
    for pf, t in sorted(((m["pfnet"] or 0, t) for t, m in res.items()), reverse=True)[:80]:
        m = res[t]
        print(t, "pfnet", pf, "pfgross", m["pfgross"], "win", m["win_pct"], "n", m["n"], "hold", m["avg_held_bars"],
              "exits", json.dumps(m["exit_reasons"], default=str))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge(sys.argv[2:])
    else:
        run()
