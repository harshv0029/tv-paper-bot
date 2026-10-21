"""O'Neil EXTENSION research batch (backlog B-467..B-480, B-484..B-487, B-490, B-492, B-494..B-500).

Complements scripts/oneil_research.py (pivot/flat-base/new-high/RS-screen + percent/ATR/target/trailing stops)
and scripts/oneil_patterns.py (cup/saucer/double-bottom). Same conventions: daily (1d) and weekly (1w) bars,
FULL NSE universe (main._load_nse_universe_from_file()), BOTH directions, signal at close of t -> entry at the
open of t+1, 0.8% round-trip cost (main.ROUND_TRIP_COST_PCT), a stop on EVERY trade (no stop-less cell),
mergeable additive cells. Short = reciprocal-price mirror (o'=1/o, h'=1/l, l'=1/h, c'=1/c, RS'=100-RS,
index'=1/index) of the same bullish detector, so every rule is tested in both directions as its own tag.

Entry families (own tags, stop sweep atr2/atr3, holds from CFG):
  oneil_hft__breakout (B-467)       high tight flag: >=+100% pole then <=20% flag, breakout
  oneil_shakeout__plus3 (B-468)     break of base low then recovery m*ATR above the broken low (m 1,2)
  oneil_baseonbase__breakout (B-469) 2nd pivot breakout 20-80 bars after a stalled (<25%) first one
  oneil_hns__neckline (B-470)       inverse H&S (long) / H&S top (short, native in the book)
  oneil_triple__neckline (B-471)    triple bottom (long) / triple top (short)
  oneil_flagprice__breakout (B-471) pole >=20% + tight flag breakout
  oneil_tightarea__breakout (B-471) 5-bar closing range <=2%/3% then breakout
  oneil_trendline__break (B-472)    break of the descending line across the last two swing highs
  oneil_pullback__buy (B-478)       within 5% of the recent high on dried-up volume above the 50-bar MA
  oneil_abnormal__strength (B-479)  stock moves >=2/3/5% against an opposite-signed index day
  oneil_leaders__firsthigh (B-480)  first 52-week high within 3 months of an index low
  oneil_rsline__newhigh (B-484)     RS line (stock/index) at a new high while price is not
  oneil_volpct__surge (B-487)       volume >= 4x / 6x the 50-bar average on a >=2% bar
Filters on the oneil_pivot__breakout trigger, tag <trigger>__x__<filter> (B-474..B-477, B-486):
  dryup, tight (3 thresholds), overhead supply, prior uptrend (+RS improving), correction ratio.
  Role-swapped ordering (filter as trigger, pivot as filter) is OWED (not built) and says so in the output.
Exit modes on the oneil_pivot__breakout trigger (initial atr3 stop always on; mode adds the exit rule):
  rswarn70/rs50/rs30 (B-485), sc (B-490 sell half -5% and rest -10%), belock15/belock20 (B-492),
  ma10w (B-494), ma200trend/ma200ext70/ma200ext100 (B-495), climaxrun/climaxvol/exhaust (B-496),
  gapup (B-497), churn/lowclose/failrally/bigbreak (B-498), ddpk12/ddpk15/giveback/nobounce (B-499),
  dull/six/noearly (B-500), base = control (stop + max-hold only).
NOT built (data missing, recorded honestly): B-481 IPO base (no listing-date feed in repo), B-482 group/cousin
stocks (no industry map).
Env: TF (1d|1w), SHARD, NSHARDS, MAXSYM. Output docs/oneil_ext_research_<tf>_s<shard>.json (cell sums);
`--merge files...` pools shards and prints pfnet/pfgross/win%/n/avg hold/exit-reason breakdown.
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
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import oneil_research as orx  # noqa: E402  (shared helpers + cell accumulators)

shift, sma, rmax, rmin, atr_arr = orx.shift, orx.sma, orx.rmax, orx.rmin, orx.atr_arr
fnum = orx.fnum

# bar-count constants change meaning with candle size (re-derived per timeframe, stated in the workflow header)
EX = {
    "1d": dict(pole=40, flag=15, sw=4, sk=10, bob_min=20, bob_max=80, dry=10, tightn=15,
               tight_thr=(0.01, 0.015, 0.02), sup_lb=250, pull=20, ma10=50, climax_n=12, fp_pole_n=10, fp_flag=8,
               tight5=5, idx_lb=120, idx_rec=63, dull=65, six=125, noearly=40, adv_lb_rs=20, corr_lb=60,
               hs_max_age=40, tl_age=60, tl_min_sep=5, trip_span=20),
    "1w": dict(pole=8, flag=3, sw=2, sk=2, bob_min=4, bob_max=16, dry=2, tightn=3,
               tight_thr=(0.03, 0.05, 0.08), sup_lb=52, pull=4, ma10=10, climax_n=3, fp_pole_n=2, fp_flag=2,
               tight5=3, idx_lb=26, idx_rec=13, dull=13, six=26, noearly=8, adv_lb_rs=4, corr_lb=12,
               hs_max_age=8, tl_age=12, tl_min_sep=2, trip_span=5),
}
STOPS = (2.0, 3.0)
ABN = (0.02, 0.03, 0.05)
SHAKE_M = (1.0, 2.0)
VOLPCT = (3.0, 5.0)
TIGHT5 = (0.02, 0.03)


def mirror(o, h, l, c, idx, rs):
    """Reciprocal-price mirror: a bullish detector run on this IS the short rule on the original series."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / o, 1.0 / l, 1.0 / h, 1.0 / c, (1.0 / idx if idx is not None else None), 100.0 - rs


def swing_pivots(h, l, sw):
    """Confirmed swing highs/lows: list of (k, price, confirm_index=k+sw). No look-ahead."""
    n = len(h)
    hi, lo = [], []
    for k in range(sw, n - sw):
        if h[k] == np.max(h[k - sw:k + sw + 1]):
            hi.append((k, h[k], k + sw))
        if l[k] == np.min(l[k - sw:k + sw + 1]):
            lo.append((k, l[k], k + sw))
    return hi, lo


def _confirmed(piv, t):
    out = []
    for p in piv:
        if p[2] <= t:
            out.append(p)
        else:
            break
    return out


def _tf_cumcount(mask):
    return np.cumsum(np.nan_to_num(np.asarray(mask, float)))


def bull_signals(o, h, l, c, v, idx, rs, cfg, ex):
    """Bullish detectors. Returns (entries {(fam,var,pkey):bool}, pivot_brk, filters {(fam,var,pkey):bool}, exits {(mode,val):bool})."""
    n = len(c)
    base, vol_n, smalt, yr = cfg["base"], cfg["vol"], cfg["smalt"], cfg["yr"]
    vavg = shift(sma(v, vol_n))
    ma = sma(c, smalt)
    ma50 = sma(c, ex["ma10"])
    atr = atr_arr(h, l, c)
    E, F, X = {}, {}, {}
    zero = np.zeros(n, bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        volok = v >= orx.VOL_MULT * vavg
        pivH = shift(rmax(h, base))
        pivL = shift(rmin(l, base))
        depth = (pivH - pivL) / pivH
        brk = (c > pivH) & volok & (c > ma) & (depth <= orx.DEPTH_MAX)
        nxt_o = shift(o, -1)
        brk_chase = brk & ((nxt_o / pivH - 1) <= 0.10)
        # --- B-467 high tight flag
        Fb, P = ex["flag"], ex["pole"]
        fH, fL = shift(rmax(h, Fb)), shift(rmin(l, Fb))
        poleLow = shift(rmin(l, P), Fb)
        E[("oneil_hft", "breakout", "na")] = (fH / poleLow >= 2.0) & ((fH - fL) / fH <= 0.20) & (c > fH) & volok
        # --- B-468 shakeout plus m*ATR
        sk = ex["sk"]
        baseLow = shift(rmin(l, base), sk)
        brokeLow = shift(rmin(l, sk))
        brokeRec = brokeLow < baseLow
        for m in SHAKE_M:
            lvl = baseLow + m * atr
            E[("oneil_shakeout", "plus3", f"m{fnum(m)}")] = brokeRec & (c > lvl) & (shift(c) <= shift(lvl)) & (c > baseLow)
        # --- B-469 base on base
        bob = zero.copy()
        brk_idx = np.flatnonzero(np.nan_to_num(brk.astype(float)) > 0)
        bset = set(brk_idx.tolist())
        for t in brk_idx:
            lo_, hi_ = t - ex["bob_max"], t - ex["bob_min"]
            prev = [u for u in brk_idx if lo_ <= u <= hi_]
            if not prev:
                continue
            t1 = prev[-1]
            lvl = pivH[t1]
            if np.isnan(lvl) or lvl <= 0:
                continue
            stall = np.nanmax(c[t1:t]) / lvl - 1
            if stall < 0.25 and c[t] > lvl:
                bob[t] = True
        E[("oneil_baseonbase", "breakout", "na")] = bob
        # --- B-470 inverse H&S (long). Short native H&S top = mirror of this.
        hi, lo = swing_pivots(h, l, ex["sw"])
        hns, trip, tl = zero.copy(), zero.copy(), zero.copy()
        age = ex["hs_max_age"]
        lo_c = lo
        for t in range(n):
            los = _confirmed(lo_c, t)
            his = _confirmed(hi, t)
            if len(los) >= 3:
                (k1, p1, _), (k2, p2, _), (k3, p3, c3) = los[-3], los[-2], los[-1]
                # inverse H&S: head (k2) lowest, shoulders higher and similar
                if p2 < p1 * 0.97 and p2 < p3 * 0.97 and abs(p1 - p3) / p1 <= 0.15 and 0 < t - c3 <= age:
                    n1 = [x[1] for x in his if k1 < x[0] < k2]
                    n2 = [x[1] for x in his if k2 < x[0] < k3]
                    if n1 and n2:
                        neck = (max(n1) + max(n2)) / 2.0
                        if c[t] > neck and (t == 0 or c[t - 1] <= neck) and volok[t]:
                            hns[t] = True
                # triple bottom: three lows within 3%, spanning trip_span bars
                lows3 = [p1, p2, p3]
                if (max(lows3) - min(lows3)) / max(lows3) <= 0.03 and k3 - k1 >= ex["trip_span"] and 0 < t - c3 <= age:
                    mid = [x[1] for x in his if k1 < x[0] < k3]
                    if mid:
                        neck = max(mid)
                        if c[t] > neck and (t == 0 or c[t - 1] <= neck) and volok[t]:
                            trip[t] = True
            # --- B-472 descending trendline across the last two swing highs
            if len(his) >= 2:
                (ka, pa, _), (kb, pb, cb) = his[-2], his[-1]
                if pb < pa and kb - ka >= ex["tl_min_sep"] and 0 < t - cb <= ex["tl_age"]:
                    line_t = pb + (pb - pa) / (kb - ka) * (t - kb)
                    line_p = pb + (pb - pa) / (kb - ka) * (t - 1 - kb)
                    if c[t] > line_t and t > 0 and c[t - 1] <= line_p:
                        tl[t] = True
        E[("oneil_hns", "neckline", "na")] = hns
        E[("oneil_triple", "neckline", "na")] = trip
        E[("oneil_trendline", "break", "na")] = tl
        # --- B-471 flag-price and tight-area
        fpn, fpf = ex["fp_pole_n"], ex["fp_flag"]
        fpH, fpL = shift(rmax(h, fpf)), shift(rmin(l, fpf))
        pole = shift(c, fpf) / shift(c, fpf + fpn) - 1
        E[("oneil_flagprice", "breakout", "na")] = (pole >= 0.20) & ((fpH - fpL) / fpH <= 0.08) & (c > fpH) & volok
        t5 = ex["tight5"]
        tH, tCmax, tCmin = shift(rmax(h, t5)), shift(rmax(c, t5)), shift(rmin(c, t5))
        for th in TIGHT5:
            E[("oneil_tightarea", "breakout", f"r{fnum(th * 100)}")] = ((tCmax - tCmin) / tCmax <= th) & (c > tH) & volok & (c > ma)
        # --- B-478 pullback buy
        Hh = shift(rmax(h, ex["pull"]))
        dry3 = sma(v, 3) < 0.75 * vavg
        E[("oneil_pullback", "buy", "na")] = (c < Hh) & (c >= 0.95 * Hh) & (Hh >= 0.97 * shift(rmax(h, yr))) & shift(dry3.astype(float)).astype(bool) & (c > ma50) & (c > o)
        # --- B-479 abnormal strength (needs index)
        # --- B-480, B-484 (need index)
        if idx is not None:
            ret = c / shift(c) - 1
            iret = idx / shift(idx) - 1
            for x in ABN:
                E[("oneil_abnormal", "strength", f"x{fnum(x * 100)}")] = (ret >= x) & (iret <= -0.003)
            nh = (c > shift(rmax(c, yr))).astype(float)
            cs = _tf_cumcount(nh)
            first_after_low = zero.copy()
            L = ex["idx_lb"]
            for t in range(L, n):
                w = idx[t - L:t + 1]
                if np.isnan(w).any():
                    continue
                pos = t - L + int(np.argmin(w))
                if t - pos <= ex["idx_rec"] and idx[t] / idx[pos] - 1 >= 0.05 and nh[t] == 1 and (cs[t - 1] - cs[pos]) == 0:
                    first_after_low[t] = True
            E[("oneil_leaders", "firsthigh", "na")] = first_after_low
            rsl = c / idx
            E[("oneil_rsline", "newhigh", "na")] = (rsl > shift(rmax(rsl, yr))) & (c < shift(rmax(c, yr))) & (c > ma)
        # --- B-487 volume % change surge
        vr = v / vavg - 1
        for th in VOLPCT:
            E[("oneil_volpct", "surge", f"v{fnum(th)}")] = (vr >= th) & (c / shift(c) - 1 >= 0.02) & (c > o)
        # ---- filters on the pivot trigger (bullish forms)
        dry_any = shift(rmin(v, ex["dry"])) < 0.5 * vavg
        F[("oneil_dryup", "volume", "na")] = dry_any
        rng = sma((h - l) / c, ex["tightn"])
        for th in ex["tight_thr"]:
            F[("oneil_tightness", "range", f"r{fnum(th * 100)}")] = shift(rng) <= th
        adv = shift(c, base) / shift(c, base + cfg["adv_lb"])
        F[("oneil_priorup", "advance", "a30")] = (adv >= 1.30) & (rs > shift(rs, ex["adv_lb_rs"]))
        sup = zero.copy()
        slb = ex["sup_lb"]
        for t in np.flatnonzero(np.nan_to_num(brk_chase.astype(float)) > 0):
            if t < 20:
                continue
            s0 = max(0, t - slb)
            cw, vw = c[s0:t], v[s0:t]
            tot = np.nansum(vw)
            if tot <= 0:
                continue
            share = np.nansum(vw[(cw > c[t]) & (cw <= c[t] * 1.25)]) / tot
            sup[t] = share <= 0.30
        F[("oneil_overhead", "supply", "s30")] = sup
        if idx is not None:
            cl = ex["corr_lb"]
            idd = idx / rmax(idx, cl) - 1
            sdd = c / rmax(c, cl) - 1
            idd_min, sdd_min = pd.Series(idd).rolling(cl, min_periods=1).min().to_numpy(), pd.Series(sdd).rolling(cl, min_periods=1).min().to_numpy()
            corr_ok = (idd_min > -0.08) | (sdd_min >= 1.75 * idd_min)
            F[("oneil_corrratio", "leader", "k1d75")] = corr_ok
        # ---- state-independent exit arrays (flags at close of j; exit at next open unless gap*)
        ma200 = ma
        rising = ma200 > shift(ma200, 5)
        X[("ma10w", 0)] = (c < ma50) & (v > vavg)
        X[("ma200trend", 0)] = (c < ma200) & ~rising
        X[("ma200ext", 70)] = c >= 1.7 * ma200
        X[("ma200ext", 100)] = c >= 2.0 * ma200
        X[("climaxrun", 0)] = (c / shift(c, ex["climax_n"]) - 1) >= 0.25
        gp = (o / shift(c) - 1) >= 0.04
        X[("gapup", 0)] = gp
        rngbar = (h - l)
        X[("churn", 0)] = (v >= 1.5 * vavg) & (np.abs(c - o) < 0.3 * atr)
        lowc = ((c - l) / np.where(rngbar > 0, rngbar, np.nan)) <= 0.25
        X[("lowclose", 0)] = pd.Series(lowc.astype(float)).rolling(5).sum().to_numpy() >= 3
        dn = c < shift(c)
        X[("failrally", 0)] = (shift(dn.astype(float), 2) == 1) & (shift(c) > shift(c, 2)) & (c > shift(c, 2)) & (c < shift(h)) & (c < shift(c))
        X[("bigbreak", 0)] = (c < o) & (v >= shift(rmax(v, yr))) & (c < shift(c))
        nb = np.ones(n, bool)
        for k in range(4):
            nb &= shift(c, k) < shift(c, k + 1)
        X[("nobounce", 0)] = nb
        X[("rswarn", 70)] = (rs < 70) & (v > vavg) & (c < shift(c))
        X[("rs50", 0)] = rs < 50
        X[("rs30", 0)] = rs < 30
    clean = lambda d: {k: np.nan_to_num(np.asarray(m, float)).astype(bool) for k, m in d.items()}
    return clean(E), np.nan_to_num(brk_chase.astype(float)).astype(bool), clean(F), clean(X)


def simulate_x(sig, o, h, l, c, v, atr, hold, stopm, mode, val, exarr, side, cost, ex):
    """Non-overlapping trades; initial ATR stop ALWAYS on. Returns [(net, gross, held, reason)]."""
    res = []
    n = len(c)
    nxt = 0
    for t in np.flatnonzero(sig):
        if t < nxt or t + 1 >= n or np.isnan(atr[t]) or atr[t] <= 0:
            continue
        e = t + 1
        ent = o[e]
        if not ent or np.isnan(ent):
            continue
        last = min(e + hold - 1, n - 1)
        if last - e + 1 < hold:
            continue
        stop = ent - side * stopm * atr[t]
        init = stop
        legs = None
        if mode == "sc":  # B-490 scaled loss cut: half at -5%, rest at -10%
            stop = ent * (1 - side * 0.10)
            legs = [ent * (1 - side * 0.05), ent * (1 - side * 0.10)]
        peak = ent
        up_max = 0.0
        exitp, jx, reason = c[last], last, "timeout"
        done_half = None
        for j in range(e, last + 1):
            if side == 1:
                hit_stop = l[j] <= stop
            else:
                hit_stop = h[j] >= stop
            if legs is not None and done_half is None:
                hit5 = (l[j] <= legs[0]) if side == 1 else (h[j] >= legs[0])
                if hit5:
                    px5 = min(legs[0], o[j]) if side == 1 else max(legs[0], o[j])
                    done_half = (px5 / ent - 1) * side
            if hit_stop:
                exitp = min(stop, o[j]) if side == 1 else max(stop, o[j])
                jx = j
                reason = "trail_stop" if (stop > init if side == 1 else stop < init) and mode == "belock" else "stop"
                break
            peak = max(peak, h[j]) if side == 1 else min(peak, l[j])
            gain_c = (c[j] / ent - 1) * side
            peak_gain = (peak / ent - 1) * side
            if mode == "belock" and peak_gain >= val / 100.0:
                stop = max(stop, ent) if side == 1 else min(stop, ent)
            if mode in ("noearly", "tgt") and (mode == "tgt" or j - e >= ex["noearly"]):
                tg = ent * (1 + side * 0.20)
                if (side == 1 and h[j] >= tg) or (side == -1 and l[j] <= tg):
                    exitp, jx, reason = (max(tg, o[j]) if side == 1 else min(tg, o[j])), j, "target"
                    break
            if j > e:
                dday = (c[j] / c[j - 1] - 1) * side
                if mode == "gapup" and exarr is not None and exarr[j]:
                    exitp, jx, reason = o[j], j, "gapup"
                    break
                trig = False
                if mode == "ddpk" and (peak_gain > 0) and (1 + gain_c) / (1 + peak_gain) - 1 <= -val / 100.0:
                    trig = True
                elif mode == "giveback" and peak_gain >= 0.20 and gain_c <= 0.2 * peak_gain:
                    trig = True
                elif mode == "climaxvol" and j - e >= 10 and v[j] >= np.max(v[e:j + 1]) and dday > 0 and gain_c > 0:
                    trig = True
                elif mode == "exhaust" and j - e >= 10 and dday > 0 and gain_c > 0 and dday > up_max:
                    trig = True
                elif mode not in ("base", "sc", "belock", "ddpk", "giveback", "climaxvol", "exhaust", "dull", "six", "noearly", "tgt", "gapup") \
                        and exarr is not None and exarr[j]:
                    trig = True
                if mode == "exhaust" and dday > 0 and j - e < 10:
                    up_max = max(up_max, dday)
                elif mode == "exhaust" and dday > 0:
                    up_max = max(up_max, dday)
                if trig:
                    if j + 1 <= last:
                        exitp, jx = o[j + 1], j + 1
                    else:
                        exitp, jx = c[j], j
                    reason = mode
                    break
            if mode == "dull" and j - e + 1 == val and abs(gain_c) < 0.05:
                exitp, jx, reason = c[j], j, "dull"
                break
            if mode == "six" and j - e + 1 >= val and gain_c < 0:
                exitp, jx, reason = c[j], j, "six_month_loser"
                break
        g = (exitp / ent - 1) * side
        if legs is not None and done_half is not None:
            g = (done_half + g) / 2.0
            reason += "+half5"
        res.append((g - cost, g, jx - e + 1, reason))
        nxt = jx + 1
    return res


def ptag(fam, var, d, tf, params):
    return orx.make_tag(fam, var, d, tf, params)


def combo(base_tag, filt_tag):
    return f"{base_tag}__x__{filt_tag}"


EXIT_MODES = (("base", 0), ("sc", 0), ("belock", 15), ("belock", 20), ("ma10w", 0), ("ma200trend", 0), ("ma200ext", 70),
              ("ma200ext", 100), ("climaxrun", 0), ("climaxvol", 0), ("exhaust", 0), ("gapup", 0), ("churn", 0),
              ("lowclose", 0), ("failrally", 0), ("bigbreak", 0), ("ddpk", 12), ("ddpk", 15), ("giveback", 0),
              ("nobounce", 0), ("rswarn", 70), ("rs50", 0), ("rs30", 0), ("dull", 65), ("six", 125), ("noearly", 40))


def _exit_key(mode, val):
    if mode == "dull":
        return None
    return (mode, val if mode in ("ma200ext", "rswarn") else 0)


def process_symbol(df, idx_series, rs_series, cfg, ex, cost, tf, cells):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = rs_series.reindex(df.index).to_numpy(float)
    idx = None
    if idx_series is not None:
        idx = idx_series.reindex(df.index).ffill().to_numpy(float)
        if np.isnan(idx).all():
            idx = None
    for d, side in (("long", 1), ("short", -1)):
        if d == "long":
            arrs = (o, h, l, c, idx, rs)
        else:
            arrs = mirror(o, h, l, c, idx, rs)
        mo, mh, ml, mc, midx, mrs = arrs
        atr = atr_arr(h, l, c)
        E, brk, F, X = bull_signals(mo, mh, ml, mc, v, midx, mrs, cfg, ex)
        holds = cfg["holds"]
        # entry families
        for (fam, var, pk), sg in E.items():
            if not sg.any():
                continue
            for hold in holds:
                for sm in STOPS:
                    rows = simulate_x(sg, o, h, l, c, v, atr, hold, sm, "base", 0, None, side, cost, ex)
                    if rows:
                        p = {"h": hold, "atr": sm}
                        if pk != "na":
                            p["p"] = pk
                        orx.acc_add(cells, ptag(fam, var, d, tf, p), rows)
        # filters on the pivot trigger (trigger first, role order 1 only)
        base_h = holds[1]
        for (ffam, fvar, fpk), fm in F.items():
            sg = brk & fm
            if not sg.any():
                continue
            rows = simulate_x(sg, o, h, l, c, v, atr, base_h, 3.0, "base", 0, None, side, cost, ex)
            if rows:
                bt = ptag("oneil_pivot", "breakout", d, tf, {"h": base_h, "atr": 3.0, "chase": 10})
                fp = {} if fpk == "na" else {"p": fpk}
                orx.acc_add(cells, combo(bt, ptag(ffam, fvar, d, tf, fp)), rows)
        # exit modes on the pivot trigger
        if brk.any():
            for mode, val in EXIT_MODES:
                if mode in ("dull", "six"):
                    hold = (ex["dull"] if mode == "dull" else ex["six"]) + 5
                elif mode == "noearly":
                    hold = holds[-1]
                else:
                    hold = holds[-1]
                key = None if mode in ("base", "sc", "belock", "ddpk", "giveback", "climaxvol", "exhaust", "dull", "six", "noearly") \
                    else (mode, val if mode in ("ma200ext", "rswarn") else 0)
                exarr = X.get(key) if key is not None else None
                if key is not None and exarr is None:
                    continue
                v2 = ex["dull"] if mode == "dull" else (ex["six"] if mode == "six" else val)
                rows = simulate_x(brk, o, h, l, c, v, atr, hold, 3.0, mode, v2, exarr, side, cost, ex)
                if rows:
                    p = {"h": hold, "atr": 3.0, "chase": 10, "xm": mode + (str(int(val)) if val else "")}
                    orx.acc_add(cells, ptag("oneil_pivot", "exit", d, tf, p), rows)


def main_run():
    import yfinance as yf
    import main as app
    tf = os.environ.get("TF", "1d")
    cfg, ex = orx.CFG[tf], EX[tf]
    shard, nsh = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    import universe_pin as up  # B-841: PIN_FILE pins the exact symbol set for a rerun
    pin_file, pin_tol = up.env_args()
    syms = up.select_universe(app._load_nse_universe_from_file(), pin_file)[shard::nsh]
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    interval = "1wk" if tf == "1w" else "1d"
    idx_series = None
    try:
        di = yf.download("^NSEI", period=cfg["period"], interval=interval, auto_adjust=True, progress=False)
        col = di["Close"]
        idx_series = (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna()
    except Exception as e:
        print("index download failed (index-dependent cells skipped):", e, flush=True)
    data = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=cfg["period"], interval=interval, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = orx.clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= cfg["min_bars"]:
                data[s] = df
        print("downloaded", b0, "kept", len(data), flush=True)
    closes = pd.DataFrame({s: df["Close"] for s, df in data.items()})
    rs_all = orx.rs_rank_matrix(closes, cfg["rs_lb"])
    cells = {}
    for i, (s, df) in enumerate(data.items()):
        process_symbol(df, idx_series, rs_all[s], cfg, ex, cost, tf, cells)
        if i % 100 == 0:
            print("processed", i, "cells", len(cells), flush=True)
    out = os.path.join(ROOT, "docs", f"oneil_ext_research_{tf}_s{shard}.json")
    json.dump({"tf": tf, "shard": shard, "nshards": nsh, "symbols": len(data), "universe_requested": len(syms), "cells": cells,
               **up.shard_meta(syms, list(data), pin_file, pin_tol)},
              open(out, "w"), default=lambda o_: o_.item() if hasattr(o_, "item") else str(o_))
    print("wrote", out, "cells", len(cells))


def merge_run(paths):
    parts = [json.load(open(p)) for p in paths]
    merged = orx.merge_cells([p["cells"] for p in parts])
    res = orx.finalize(merged)
    import cell_tsv  # B-783: keep-all-data, every cell (min_n=1), full table in the log
    cell_tsv.emit_full(orx.finalize(merged, min_n=1), os.environ.get("TSV_OUT", os.path.join(ROOT, "docs", "oneil_ext_research_cells.tsv")), "oneil_ext_research")
    uni = sum(p.get("symbols", 0) for p in parts)
    out = os.path.join(ROOT, "docs", "oneil_ext_research_results.json")
    import universe_pin as up
    json.dump({"universe_symbols": uni, "fetched_symbols": up.merge_fetched(parts), "owed": ["role-swapped filter-as-trigger ordering", "B-481 IPO base (no listing dates)", "B-482 group stocks (no industry map)", "4h/1h not applicable (daily/weekly rules)"], "results": res},
              open(out, "w"), indent=0, default=lambda o_: o_.item() if hasattr(o_, "item") else str(o_))
    ok = sorted([(m["pfnet"], m["n"], t) for t, m in res.items() if m["pfnet"] and m["pfnet"] >= 1.0 and m["n"] >= 300], reverse=True)
    print(f"universe_symbols={uni} cells={len(res)} viable(PFnet>=1.0,n>=300)={len(ok)}")
    for pf, n, t in ok[:60]:
        m = res[t]
        print(f"{t} pfnet={pf} pfgross={m['pfgross']} win={m['win_pct']} n={n} hold={m['avg_held_bars']} reasons={json.dumps(m['exit_reasons'], default=str)}")
    print("TOP15 any n>=100:")
    for pf, t in sorted(((m["pfnet"] or 0, t) for t, m in res.items() if m["n"] >= 100), reverse=True)[:15]:
        print(t, pf, res[t]["pfgross"], res[t]["win_pct"], res[t]["n"], res[t]["avg_held_bars"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge_run(sys.argv[2:])
    else:
        main_run()
