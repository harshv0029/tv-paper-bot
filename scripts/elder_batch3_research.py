#!/usr/bin/env python3
"""Elder "Trading for a Living" research, batch 3 (the rows batch 1/2 and breadth_lab did not reach).

Research only: no live wiring, no main.py edits. Reuses scripts/elder_indicators_research.py
(indicators, tag grammar, aggregation, PFnet summary). Every variant runs BOTH directions, ATR
stop sweep 1.5/2/3 with a stop on EVERY trade, 0.8% round-trip cost, next-bar-open entry,
30-bar max hold, FULL universe via main._load_nse_universe_from_file().

Families (one workflow job each x shards):
  osc      B-641 B-644 B-645 B-646 B-656 B-657 B-661 B-662 B-666 B-677 B-678 B-728
           oscillator reversal triggers, S-RoC(13/21), RoC peak exit, RoC/RSI trendline breaks,
           stochastic bottom shape, weekly-stoch lead, RSI reversal pattern, volume-trend filter,
           divergence classes A/B/C, percentile-calibrated OB/OS lines
  struct   B-676 B-679 B-741 B-704 B-706 B-707 B-710 B-673 B-685 B-735
           retracement entries, minor-swing / bar-low stop placement, Triple Screen exits,
           Parabolic regime + stop-and-reverse, factor-of-5 multi-timeframe gate, FFT cycle gate
  chan     B-720 B-721 B-722 B-733 B-734 B-767
           Appel channel, sigma-band squeeze, Plummer range targets, chart patterns (double
           top/bottom, H&S + failed H&S, rectangle, triangles), pivot trendline breaks
  orb      B-736   opening-range breakout (intraday bars only; run with interval=5m)
  sizing   B-744 B-745   optimal f, capped 2%, half-f and martingale (negative control) on
           per-symbol R-multiple trade streams (flagged proxy: R = ret / (2*median ATR%))
  breadth  B-670 B-680 B-681 B-682 B-683 B-684 B-731   cross-sectional: A/D, NH-NL, TRIN, Climax,
           Most Active Stocks from the FULL universe, traded on ^NSEI (sharded partial sums)

Not built here (see docs/closure_patch_agent3.json): B-742 (multi-unit pyramiding), B-743 and
B-746 (need a dated portfolio ledger the single-position simulators do not produce).

Usage:
  python3 scripts/elder_batch3_research.py --family osc --shard 0 --nshards 4 --out out/
  python3 scripts/elder_batch3_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import glob
import heapq
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import elder_indicators_research_ext as ext  # noqa: E402

FAMILIES = ("osc", "struct", "chan", "orb", "sizing", "breadth")
SIG_FAMILIES = ("osc", "struct", "chan", "orb")
MAX_HOLD = er.MAX_HOLD_BARS
COST = er.COST_ROUND_TRIP
HTF_RULE = {"1d": "W-FRI", "1h": "D", "15m": "1h", "5m": "1h"}   # factor ~5 (flagged where not)


# ---------------------------------------------------------------- helpers
def B(x):
    return np.asarray(pd.Series(x).fillna(False), dtype=bool)


def sig_pack(df, long, short, ex_l=None, ex_s=None, stop_l=None, stop_s=None, tgt_l=None, tgt_s=None):
    n = len(df)
    nan = np.full(n, np.nan)
    z = np.zeros(n, dtype=bool)
    f = lambda a: nan if a is None else np.asarray(a, float)  # noqa: E731
    return {"long": B(long), "short": B(short),
            "exit_long": z if ex_l is None else B(ex_l), "exit_short": z if ex_s is None else B(ex_s),
            "stop_long": f(stop_l), "stop_short": f(stop_s), "tgt_long": f(tgt_l), "tgt_short": f(tgt_s)}


def edge(s):
    s = pd.Series(s).fillna(False).astype(bool)
    return s & ~s.shift(1, fill_value=False)


def pivot_list(x, w, kind):
    """-> list of (confirmed_index, pivot_index, value); confirmation lags by w bars (no look-ahead)."""
    s = pd.Series(x, dtype=float)
    ref = s.rolling(2 * w + 1, center=True).max() if kind == "high" else s.rolling(2 * w + 1, center=True).min()
    out, last = [], -10
    for i in np.flatnonzero((s.to_numpy() == ref.to_numpy()) & ~np.isnan(ref.to_numpy())):
        if i - last <= w:
            continue
        last = i
        out.append((i + w, i, float(s.iloc[i])))
    return out


def trendline_break(x, w=3):
    """Down-trendline through the last two confirmed pivot highs (second lower) -> up_break when x
    closes above it; up-trendline through last two pivot lows (second higher) -> dn_break."""
    x = np.asarray(x, float)
    n = len(x)
    hi, lo = pivot_list(x, w, "high"), pivot_list(x, w, "low")
    up, dn = np.zeros(n, bool), np.zeros(n, bool)
    hc, lc = {c: (p, v) for c, p, v in hi}, {c: (p, v) for c, p, v in lo}
    H, L = [], []
    for i in range(1, n):
        if i in hc:
            H.append(hc[i])
        if i in lc:
            L.append(lc[i])
        if len(H) >= 2 and H[-1][1] < H[-2][1] and H[-1][0] > H[-2][0]:
            (p1, v1), (p2, v2) = H[-2], H[-1]
            sl = (v2 - v1) / (p2 - p1)
            line, prev = v2 + sl * (i - p2), v2 + sl * (i - 1 - p2)
            if x[i] > line and x[i - 1] <= prev:
                up[i] = True
        if len(L) >= 2 and L[-1][1] > L[-2][1] and L[-1][0] > L[-2][0]:
            (p1, v1), (p2, v2) = L[-2], L[-1]
            sl = (v2 - v1) / (p2 - p1)
            line, prev = v2 + sl * (i - p2), v2 + sl * (i - 1 - p2)
            if x[i] < line and x[i - 1] >= prev:
                dn[i] = True
    return up, dn


def div_classes(price_hi, price_lo, osc, w=3, maxgap=40, tol=0.005, otol=1.0):
    """Elder divergence classes A/B/C on pivots of price; signal at pivot confirmation.
    A: price new extreme, osc less extreme. B: price double top/bottom, osc less extreme.
    C: price new extreme, osc double top/bottom. -> dict class -> (long, short)."""
    n = len(osc)
    osc = np.asarray(osc, float)
    out = {k: (np.zeros(n, bool), np.zeros(n, bool)) for k in "abc"}
    for kind, series, side in (("low", price_lo, 0), ("high", price_hi, 1)):
        pv = pivot_list(series, w, kind)
        for a, b in zip(pv[:-1], pv[1:]):
            (_, p1, v1), (c2, p2, v2) = a, b
            if p2 - p1 > maxgap or c2 >= n or np.isnan(osc[p1]) or np.isnan(osc[p2]):
                continue
            o1, o2 = osc[p1], osc[p2]
            sgn = 1 if side == 0 else -1               # long: lower low; short: higher high
            new_ext = sgn * (v1 - v2) > tol * v1
            double = abs(v2 - v1) <= tol * v1
            osc_less = sgn * (o2 - o1) > 0
            osc_double = abs(o2 - o1) <= otol
            if new_ext and osc_less:
                out["a"][side][c2] = True
            if double and osc_less:
                out["b"][side][c2] = True
            if new_ext and osc_double:
                out["c"][side][c2] = True
    return {k: (v[0], v[1]) for k, v in out.items()}


BAD_TICK_LO, BAD_TICK_HI = 0.5, 2.0   # B-864: a >2x / <0.5x one-bar move in Open or Close vs prior Close is a data glitch


def bad_bar_mask(o, c):
    """True where Open or Close jumps outside [0.5x, 2x] of the previous Close (corrupt/unadjusted yfinance
    bar). B-864: one such bar flipped kb_oscrsi PFnet 0.958 -> 2.433 (a single ~+800x return trade)."""
    bad = np.zeros(len(c), dtype=bool)
    if len(c) < 2:
        return bad
    pc = c[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ro, rc = o[1:] / pc, c[1:] / pc
    ok = (ro >= BAD_TICK_LO) & (ro <= BAD_TICK_HI) & (rc >= BAD_TICK_LO) & (rc <= BAD_TICK_HI)
    bad[1:] = ~ok
    return bad


def sim2(df, entry, direction, am, stop_lvl=None, tgt_lvl=None, exit_bool=None, max_hold=MAX_HOLD, cost=COST):
    """Like er.simulate but with an optional structure stop (tighter of it and the ATR cap) and a
    per-signal limit target. A stop is ALWAYS present (ATR cap)."""
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    n = len(df)
    bad = bad_bar_mask(o, c)
    trades, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px = o[e]
        if px <= 0 or bad[e]:
            continue
        stop = px - d * am * a[s]
        if stop_lvl is not None and not np.isnan(stop_lvl[s]):
            stop = max(stop, stop_lvl[s]) if d == 1 else min(stop, stop_lvl[s])
        if (d == 1 and stop >= px) or (d == -1 and stop <= px):
            continue
        tg = np.nan if tgt_lvl is None else tgt_lvl[s]
        if not np.isnan(tg) and ((d == 1 and tg <= px) or (d == -1 and tg >= px)):
            continue
        exit_px, reason, j = None, None, e
        glitch = False
        for j in range(e, min(n, e + max_hold + 1)):
            if bad[j]:
                glitch = True
                break
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                g = o[j] if j > e else None
                exit_px = (min(g, stop) if d == 1 else max(g, stop)) if g is not None else stop
                reason = "stop_loss"
                break
            if not np.isnan(tg) and ((d == 1 and h[j] >= tg) or (d == -1 and l[j] <= tg)):
                exit_px, reason = tg, "target"
                break
            if exit_bool is not None and exit_bool[j] and j > e:
                exit_px, reason = c[j], "rule_exit"
                break
            if j == e + max_hold:
                exit_px, reason = c[j], "max_hold_timeout"
                break
        if glitch:
            free = j
            continue
        if exit_px is None:
            exit_px, reason, j = c[n - 1], "data_end", n - 1
        trades.append({"ret": float(d * (exit_px - px) / px - cost), "hold": int(j - e + 1), "reason": reason})
        free = j
    return trades


def htf_slope(df, tf, n=13):
    """Slope sign of the EMA(n) of the higher timeframe (factor ~5), completed bars only."""
    r = HTF_RULE.get(tf, "W-FRI")
    hc = df["Close"].resample(r).last().dropna()
    e = er.ema(hc, n)
    return np.sign(e.diff()).shift(1).reindex(df.index, method="ffill")


# ---------------------------------------------------------------- osc family
def v_reversal(df, osc="stoch", lo=20, hi=80):
    if osc == "stoch":
        x = er.stochastic(df, 5, 3)
    elif osc == "rsi":
        x = ext.rsi_wilder(df["Close"], 14)
    else:
        x = ext.williams_r(df, 7) + 100                  # -100..0 -> 0..100
    long = (x.shift(1) < lo) & (x >= lo)
    short = (x.shift(1) > hi) & (x <= hi)
    return sig_pack(df, long, short, x > 50, x < 50)


def v_sroc(df, el=13, rl=21):
    s = er.ema(df["Close"], el)
    s = s / s.shift(rl)
    turn_up, turn_dn = (s > s.shift(1)) & (s.shift(1) <= s.shift(2)), (s < s.shift(1)) & (s.shift(1) >= s.shift(2))
    return sig_pack(df, turn_up & (s < 1), turn_dn & (s > 1), turn_dn, turn_up)


def v_roc_peak_exit(df, n=7, lb=10):
    base = er.v_ema13(df)
    c = df["Close"]
    roc = c / c.shift(n)
    hi_px, lo_px = c >= c.rolling(lb).max(), c <= c.rolling(lb).min()
    bear = hi_px & (roc < roc.shift(1).rolling(lb).max())
    bull = lo_px & (roc > roc.shift(1).rolling(lb).min())
    return sig_pack(df, base["long"], base["short"], bear, bull)


def v_roc_trendline(df, src="roc", w=3):
    c = df["Close"]
    x = (c / c.shift(7)).to_numpy() if src == "roc" else ext.rsi_wilder(c, 14).to_numpy()
    up, dn = trendline_break(np.nan_to_num(x, nan=1.0), w)
    _, upt, dnt = er._ema_state(df, 26)
    return sig_pack(df, up & B(upt), dn & B(dnt), dn, up)


def v_stoch_shape(df, mode="narrow_shallow"):
    st = er.stochastic(df, 5, 3).to_numpy()
    n = len(st)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    for arr, lo_side in ((long, True), (short, False)):
        inz, w, ext_v = False, 0, 0.0
        for i in range(1, n):
            v = st[i]
            if np.isnan(v):
                continue
            z = v < 20 if lo_side else v > 80
            if z:
                if not inz:
                    inz, w, ext_v = True, 0, v
                w += 1
                ext_v = min(ext_v, v) if lo_side else max(ext_v, v)
            elif inz:
                depth = ext_v if lo_side else 100 - ext_v      # distance beyond the extreme
                narrow, shallow = w <= 3, depth >= 10
                good = narrow and shallow
                bad = (not narrow) and (not shallow)
                if (mode == "narrow_shallow" and good) or (mode == "deep_wide" and bad):
                    arr[i] = True
                inz, w = False, 0
    return sig_pack(df, long, short, st > 70, st < 30)


def v_weekly_stoch_lead(df):
    wk = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    st = er.stochastic(wk, 5, 3)
    turn_up = ((st > st.shift(1)) & (st.shift(1) <= st.shift(2)) & (st < 30)).shift(1)
    turn_dn = ((st < st.shift(1)) & (st.shift(1) >= st.shift(2)) & (st > 70)).shift(1)
    h = er.macd_hist(wk["Close"])
    still_dn, still_up = (h < h.shift(1)).shift(1), (h > h.shift(1)).shift(1)     # MACD-H lags the stoch turn
    f = lambda s: s.reindex(df.index, method="ffill").fillna(False).astype(bool)  # noqa: E731
    long = edge(f(turn_up & still_dn))
    short = edge(f(turn_dn & still_up))
    return sig_pack(df, long, short, f(turn_dn), f(turn_up))


def v_rsi_pattern(df, n=14):
    r = ext.rsi_wilder(df["Close"], n)
    cls = div_classes(df["High"].to_numpy(), df["Low"].to_numpy(), r.fillna(50).to_numpy(), 3, 40)
    lo_zone, hi_zone = (r < 40).to_numpy(), (r > 60).to_numpy()
    long, short = cls["a"][0] & lo_zone, cls["a"][1] & hi_zone
    return sig_pack(df, long, short, r > 60, r < 40)


def v_volume_trend(df, filt=True):
    base = er.v_ema13(df)
    v = df["Volume"]
    ve = er.ema(v, 5)
    ok = (ve > ve.shift(1)) & (v > v.shift(1)) if filt else pd.Series(True, index=df.index)
    return sig_pack(df, base["long"] & B(ok), base["short"] & B(ok), base["exit_long"], base["exit_short"])


def v_diverge_class(df, klass="a", osc="rsi"):
    c = df["Close"]
    x = ext.rsi_wilder(c, 14) if osc == "rsi" else er.macd_hist(c)
    cls = div_classes(df["High"].to_numpy(), df["Low"].to_numpy(), x.fillna(0).to_numpy(), 3, 40,
                      otol=1.0 if osc == "rsi" else 0.02 * float(np.nanmedian(np.abs(x))))
    lg, sh = cls[klass]
    return sig_pack(df, lg, sh)


def v_calibrated(df, q=5):
    r = ext.rsi_wilder(df["Close"], 7)
    # lines recomputed every 63 bars (3 months) from the prior 120 bars (~5-6 months): no look-ahead
    lo = r.shift(1).rolling(120).quantile(q / 100.0)
    hi = r.shift(1).rolling(120).quantile(1 - q / 100.0)
    blk = (np.arange(len(r)) // 63)
    lo = lo.groupby(blk).transform("first")
    hi = hi.groupby(blk).transform("first")
    _, up, dn = er._ema_state(df, 26)
    long = (r.shift(1) < lo) & (r >= lo) & up
    short = (r.shift(1) > hi) & (r <= hi) & dn
    return sig_pack(df, long, short, r > 60, r < 40)


# ---------------------------------------------------------------- struct family
def v_retrace(df, ratio=0.5, time_mode=False, w=3):
    n = len(df)
    c, hi, lo = df["Close"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float)
    _, up, dn = er._ema_state(df, 26)
    ph, pl = pivot_list(hi, w, "high"), pivot_list(lo, w, "low")
    hc, lc = {x[0]: x for x in ph}, {x[0]: x for x in pl}
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    H = L = None
    for i in range(n):
        if i in hc:
            H = hc[i]
        if i in lc:
            L = lc[i]
        if H is None or L is None:
            continue
        if L[1] < H[1] and H[0] <= i and up.iloc[i] and c[i] < H[2]:           # rally L->H, buy the pullback
            rng = H[2] - L[2]
            hit = (H[1] + (H[1] - L[1]) * ratio <= i) if time_mode else (lo[i] <= H[2] - ratio * rng < c[i] and i > H[1])
            if hit and c[i] > L[2]:
                long[i] = True
        if H[1] < L[1] and L[0] <= i and dn.iloc[i] and c[i] > L[2]:            # decline H->L, short the bounce
            rng = H[2] - L[2]
            hit = (L[1] + (L[1] - H[1]) * ratio <= i) if time_mode else (hi[i] >= L[2] + ratio * rng > c[i] and i > L[1])
            if hit and c[i] < H[2]:
                short[i] = True
    return sig_pack(df, edge(long), edge(short), dn, up)


def v_minor_stop(df, lb=3):
    base = er.v_ema13(df)
    stop_l = df["Low"].rolling(lb).min().to_numpy()
    stop_s = df["High"].rolling(lb).max().to_numpy()
    return sig_pack(df, base["long"], base["short"], base["exit_long"], base["exit_short"], stop_l, stop_s)


def v_ts_exit(df, mode="weekly"):
    ts = er.v_triple_screen(df, "fi", 5, "all")
    fi = er.force_index2(df)
    st = er.stochastic(df, 5, 3)
    if mode == "weekly":
        ex_l, ex_s = ts["exit_long"], ts["exit_short"]
    elif mode == "fi2":
        ex_l, ex_s = B(fi > 0), B(fi < 0)
    else:
        ex_l, ex_s = B(st > 70), B(st < 30)
    p = sig_pack(df, ts["long"], ts["short"], ex_l, ex_s)
    p["long_lvl"], p["short_lvl"] = ts["long_lvl"], ts["short_lvl"]
    return p


def v_sar(df, regime=False, reverse=True, whip=5, good=8):
    _, tr = ext.parabolic_sar(df)
    t = tr.to_numpy()
    n = len(t)
    flip_up = (t == 1) & (np.r_[0, t[:-1]] == -1)
    flip_dn = (t == -1) & (np.r_[0, t[:-1]] == 1)
    active = np.ones(n, bool)
    if regime:
        flips = np.flatnonzero(flip_up | flip_dn)
        act, bad, ok = True, 0, 0
        for a, b in zip(flips[:-1], flips[1:]):
            L = b - a
            if act:
                bad = bad + 1 if L <= whip else 0
                if bad >= 2:
                    act, ok = False, 0
            else:
                ok = ok + 1 if L >= good else 0
                if ok >= 2:
                    act, bad = True, 0
            active[b:] = act
    long, short = flip_up & active, flip_dn & active
    if reverse:
        return sig_pack(df, long, short, flip_dn, flip_up)
    return sig_pack(df, long, short)


def v_mtf(df, tf, mode="gate"):
    base = er.v_ema13(df)
    s = htf_slope(df, tf)
    if mode == "gate":
        lg, sh = B(s > 0), B(s < 0)
    else:                                              # control: trade AGAINST the higher timeframe
        lg, sh = B(s < 0), B(s > 0)
    return sig_pack(df, base["long"] & lg, base["short"] & sh, base["exit_long"], base["exit_short"])


def cycle_power(close, win=64):
    x = np.asarray(close, float)
    n = len(x)
    out = np.full(n, np.nan)
    hann = np.hanning(win)
    for i in range(win, n):
        seg = x[i - win:i]
        seg = (seg - np.polyval(np.polyfit(np.arange(win), seg, 1), np.arange(win))) * hann
        p = np.abs(np.fft.rfft(seg)) ** 2
        k = np.arange(len(p))
        band = (k >= win // 20) & (k <= win // 8)       # periods ~8..20 bars
        tot = p[1:].sum()
        out[i] = p[band].max() / tot if tot > 0 else np.nan
    return out


def v_cycle(df, thr=0.3):
    base = er.v_ema13(df)
    pw = pd.Series(cycle_power(df["Close"].to_numpy()), index=df.index)
    ok = B(pw > thr)
    return sig_pack(df, base["long"] & ok, base["short"] & ok, base["exit_long"], base["exit_short"])


# ---------------------------------------------------------------- chan family
def v_appel(df, mode="pullback", q=95):
    c, h, l = df["Close"], df["High"], df["Low"]
    e = er.ema(c, 21)
    up_dev = ((h - e) / e).shift(1).rolling(100).quantile(q / 100.0)
    dn_dev = ((e - l) / e).shift(1).rolling(100).quantile(q / 100.0)
    upper, lower = e * (1 + up_dev), e * (1 - dn_dev)
    e13, up13, dn13 = er._ema_state(df, 13)
    rising, falling = (e > e.shift(3)) & up13, (e < e.shift(3)) & dn13
    if mode == "pullback":
        long, short = rising & (l <= e13) & (c > e13 * 0.985), falling & (h >= e13) & (c < e13 * 1.015)
        return sig_pack(df, long, short, h >= upper, l <= lower, tgt_l=upper.to_numpy(), tgt_s=lower.to_numpy())
    long, short = rising & (c > upper), falling & (c < lower)
    return sig_pack(df, edge(long), edge(short), c < e13, c > e13)


def v_sigma_band(df, m=2.0, sq=0.2):
    c = df["Close"]
    e = er.ema(c, 21)
    sd = np.sqrt(((c - e) ** 2).rolling(21).mean())
    up_b, lo_b = e + m * sd, e - m * sd
    width = (2 * m * sd) / e
    narrow = width.shift(1) <= width.shift(1).rolling(120).quantile(sq)
    recent = narrow.rolling(5).max().fillna(0).astype(bool)
    long, short = recent & (c > up_b), recent & (c < lo_b)
    return sig_pack(df, edge(long), edge(short), c < e, c > e)


def v_plummer(df, k=1.618, nb=20):
    c, h, l = df["Close"], df["High"], df["Low"]
    hi, lo = h.shift(1).rolling(nb).max(), l.shift(1).rolling(nb).min()
    H = hi - lo
    long, short = (c > hi) & (c.shift(1) <= hi), (c < lo) & (c.shift(1) >= lo)
    return sig_pack(df, long, short, tgt_l=(hi + k * H).to_numpy(), tgt_s=(lo - k * H).to_numpy(),
                    stop_l=lo.to_numpy(), stop_s=hi.to_numpy())


def v_double(df, w=3, tol=0.02, maxgap=60):
    n = len(df)
    c, hi, lo = df["Close"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    tl, ts_, sl, ss = (np.full(n, np.nan) for _ in range(4))
    for kind, arr, other in (("low", lo, hi), ("high", hi, lo)):
        pv = pivot_list(arr, w, kind)
        for a, b in zip(pv[:-1], pv[1:]):
            (_, p1, v1), (c2, p2, v2) = a, b
            if p2 - p1 > maxgap or abs(v2 - v1) > tol * v1 or p2 - p1 < 5:
                continue
            seg = other[p1:p2 + 1]
            neck = seg.max() if kind == "low" else seg.min()
            for i in range(c2, min(n, p2 + maxgap)):
                if (kind == "low" and c[i] > neck) or (kind == "high" and c[i] < neck):
                    ht = abs(neck - min(v1, v2)) if kind == "low" else abs(max(v1, v2) - neck)
                    if kind == "low":
                        long[i], tl[i], sl[i] = True, neck + ht, min(v1, v2)
                    else:
                        short[i], ts_[i], ss[i] = True, neck - ht, max(v1, v2)
                    break
    return sig_pack(df, long, short, tgt_l=tl, tgt_s=ts_, stop_l=sl, stop_s=ss)


def _hs(df, w=3, tol=0.05):
    """Head-and-shoulders (short) and inverse (long) detections.
    -> list of dicts(conf, break_i, neck_slope info, head, side, target)"""
    c, hi, lo = df["Close"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float)
    n = len(df)
    ev = []
    for kind, arr, trough in (("high", hi, lo), ("low", lo, hi)):
        pv = pivot_list(arr, w, kind)
        for a, b, d in zip(pv[:-2], pv[1:-1], pv[2:]):
            (_, p1, v1), (_, p2, v2), (c3, p3, v3) = a, b, d
            if p3 - p1 > 80:
                continue
            head_ok = (v2 > v1 and v2 > v3) if kind == "high" else (v2 < v1 and v2 < v3)
            if not head_ok or abs(v3 - v1) > tol * v1:
                continue
            t1 = trough[p1:p2 + 1].min() if kind == "high" else trough[p1:p2 + 1].max()
            t2 = trough[p2:p3 + 1].min() if kind == "high" else trough[p2:p3 + 1].max()
            neck = (t1 + t2) / 2
            for i in range(c3, min(n, p3 + 25)):
                if (kind == "high" and c[i] < neck) or (kind == "low" and c[i] > neck):
                    ev.append({"i": i, "head": v2, "neck": neck, "side": "short" if kind == "high" else "long"})
                    break
    return ev


def v_hs(df, failed=False):
    n = len(df)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    tl, ts_, sl, ss = (np.full(n, np.nan) for _ in range(4))
    c = df["Close"].to_numpy(float)
    for e in _hs(df):
        i, head, neck = e["i"], e["head"], e["neck"]
        if not failed:
            if e["side"] == "short":
                short[i], ts_[i], ss[i] = True, neck - (head - neck), head
            else:
                long[i], tl[i], sl[i] = True, neck + (neck - head), head
        else:                                           # Hound of the Baskervilles: stop-and-reverse
            for j in range(i + 1, min(n, i + 30)):
                if e["side"] == "short" and c[j] > head:
                    long[j] = True
                    break
                if e["side"] == "long" and c[j] < head:
                    short[j] = True
                    break
    return sig_pack(df, long, short, tgt_l=tl, tgt_s=ts_, stop_l=sl, stop_s=ss)


def v_rect_tri(df, kind="rectangle", w=3, tol=0.02):
    n = len(df)
    c = df["Close"].to_numpy(float)
    hi, lo = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    ph, pl = pivot_list(hi, w, "high"), pivot_list(lo, w, "low")
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    tl, ts_ = np.full(n, np.nan), np.full(n, np.nan)
    hc, lc = {x[0]: x for x in ph}, {x[0]: x for x in pl}
    H, L = [], []
    for i in range(n):
        if i in hc:
            H.append(hc[i])
        if i in lc:
            L.append(lc[i])
        if len(H) < 2 or len(L) < 2:
            continue
        (h1, h2), (l1, l2) = (H[-2], H[-1]), (L[-2], L[-1])
        if i - min(h1[1], l1[1]) > 80:
            continue
        flat_h, flat_l = abs(h2[2] - h1[2]) <= tol * h1[2], abs(l2[2] - l1[2]) <= tol * l1[2]
        if kind == "rectangle":
            ok = flat_h and flat_l
        elif kind == "ascending":
            ok = flat_h and l2[2] > l1[2] * (1 + tol / 2)
        elif kind == "descending":
            ok = flat_l and h2[2] < h1[2] * (1 - tol / 2)
        else:                                                      # symmetrical
            ok = h2[2] < h1[2] * (1 - tol / 2) and l2[2] > l1[2] * (1 + tol / 2)
        if not ok:
            continue
        top, bot = max(h1[2], h2[2]), min(l1[2], l2[2])
        if c[i] > top and c[i - 1] <= top:
            long[i], tl[i] = True, top + (top - bot)
        elif c[i] < bot and c[i - 1] >= bot:
            short[i], ts_[i] = True, bot - (top - bot)
    sl = df["Low"].rolling(10).min().to_numpy()
    ss = df["High"].rolling(10).max().to_numpy()
    return sig_pack(df, long, short, tgt_l=tl, tgt_s=ts_, stop_l=sl, stop_s=ss)


def v_pivot_trendline(df, w=3):
    up, dn = trendline_break(df["Close"].to_numpy(float), w)
    return sig_pack(df, up, dn)


def v_orb(df, kbars=2):
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or (idx.normalize() == idx).all():
        raise ValueError("intraday bars required")
    day = pd.Series(idx.date, index=idx)
    pos = df.groupby(day.values).cumcount().to_numpy()
    hi_r = df["High"].where(pos < kbars).groupby(day.values).transform("max")
    lo_r = df["Low"].where(pos < kbars).groupby(day.values).transform("min")
    c = df["Close"]
    after = pos >= kbars
    brk_up, brk_dn = (c > hi_r) & after, (c < lo_r) & after
    # first breakout per day only
    long = brk_up & (brk_up.groupby(day.values).cumsum() == 1)
    short = brk_dn & (brk_dn.groupby(day.values).cumsum() == 1)
    last_bar = np.r_[day.to_numpy()[1:] != day.to_numpy()[:-1], True]
    return sig_pack(df, long, short, last_bar, last_bar, stop_l=lo_r.to_numpy(), stop_s=hi_r.to_numpy())


# ---------------------------------------------------------------- variant tables
def variant_specs(family, tf="1d"):
    S = []
    if family == "osc":
        for o, lo, hi in (("stoch", 20, 80), ("stoch", 30, 70), ("rsi", 30, 70), ("rsi", 20, 80),
                          ("wr", 10, 90), ("wr", 20, 80)):
            S.append(("reversal", {"osc": o, "lo": lo, "hi": hi}, lambda d, o=o, lo=lo, hi=hi: v_reversal(d, o, lo, hi)))
        for el, rl in ((13, 21), (8, 21), (21, 21), (13, 13)):
            S.append(("sroc", {"el": el, "rl": rl}, lambda d, el=el, rl=rl: v_sroc(d, el, rl)))
        for lb in (5, 10, 20):
            S.append(("roc_peak_exit", {"lb": lb}, lambda d, lb=lb: v_roc_peak_exit(d, 7, lb)))
        for src in ("roc", "rsi"):
            for w in (3, 5):
                S.append(("tl_break", {"src": src, "w": w}, lambda d, src=src, w=w: v_roc_trendline(d, src, w)))
        S.append(("stoch_shape", {"m": "narrowshallow"}, lambda d: v_stoch_shape(d, "narrow_shallow")))
        S.append(("stoch_shape", {"m": "deepwide"}, lambda d: v_stoch_shape(d, "deep_wide")))
        S.append(("wk_stoch_lead", {"w": 1}, v_weekly_stoch_lead))
        S.append(("rsi_pattern", {"n": 14}, v_rsi_pattern))
        S.append(("vol_trend", {"f": 1}, lambda d: v_volume_trend(d, True)))
        S.append(("vol_trend", {"f": 0}, lambda d: v_volume_trend(d, False)))
        for k in "abc":
            for o in ("rsi", "macdh"):
                S.append(("div_class", {"k": k, "osc": o}, lambda d, k=k, o=o: v_diverge_class(d, k, o)))
        for q in (5, 10):
            S.append(("calibrated_ob", {"q": q}, lambda d, q=q: v_calibrated(d, q)))
    elif family == "struct":
        for r in (0.5, 0.618):
            S.append(("retrace", {"r": r, "t": 0}, lambda d, r=r: v_retrace(d, r, False)))
        S.append(("retrace", {"r": 0.5, "t": 1}, lambda d: v_retrace(d, 0.5, True)))
        for lb in (2, 3, 5):
            S.append(("minor_stop", {"lb": lb}, lambda d, lb=lb: v_minor_stop(d, lb)))
        for m in ("weekly", "fi2", "stoch70"):
            S.append(("ts_exit", {"m": m}, lambda d, m=m: v_ts_exit(d, m)))
        S.append(("sar", {"reg": 0, "rev": 1}, lambda d: v_sar(d, False, True)))
        S.append(("sar", {"reg": 0, "rev": 0}, lambda d: v_sar(d, False, False)))
        S.append(("sar", {"reg": 1, "rev": 1}, lambda d: v_sar(d, True, True)))
        S.append(("mtf", {"m": "gate"}, lambda d, tf=tf: v_mtf(d, tf, "gate")))
        S.append(("mtf", {"m": "against"}, lambda d, tf=tf: v_mtf(d, tf, "against")))
        for thr in (0.3, 0.4):
            S.append(("cycle_gate", {"thr": thr}, lambda d, thr=thr: v_cycle(d, thr)))
    elif family == "chan":
        for q in (90, 95):
            S.append(("appel_pullback", {"q": q}, lambda d, q=q: v_appel(d, "pullback", q)))
            S.append(("appel_penetrate", {"q": q}, lambda d, q=q: v_appel(d, "penetrate", q)))
        for m in (1.5, 2.0, 2.5):
            for sq in (0.1, 0.2):
                S.append(("sigma_squeeze", {"m": m, "sq": sq}, lambda d, m=m, sq=sq: v_sigma_band(d, m, sq)))
        for k in (1.618, 2.618, 4.236):
            S.append(("plummer", {"k": k}, lambda d, k=k: v_plummer(d, k)))
        S.append(("double_tb", {"tol": 0.02}, v_double))
        S.append(("head_shoulders", {"f": 0}, lambda d: v_hs(d, False)))
        S.append(("head_shoulders", {"f": 1}, lambda d: v_hs(d, True)))
        for kd in ("rectangle", "ascending", "descending", "symmetrical"):
            S.append(("tri_" + kd, {"w": 3}, lambda d, kd=kd: v_rect_tri(d, kd)))
        for w in (3, 5):
            S.append(("pivot_tl_break", {"w": w}, lambda d, w=w: v_pivot_trendline(d, w)))
    elif family == "orb":
        for k, mins in ((1, 5), (2, 10), (3, 15), (6, 30)):
            S.append(("opening_range", {"min": mins}, lambda d, k=k: v_orb(d, k)))
    else:
        raise ValueError(family)
    return S


def run_symbol(df, family, tf, aggs):
    for variant, params, fn in variant_specs(family, tf):
        try:
            sig = fn(df)
        except Exception as ex:
            print("VARIANT ERROR", family, variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag(family, variant, direction, tf, {**params, "atr": am})
                er.add_trades(aggs.setdefault(tag, er.new_agg()), sim2(
                    df, sig[direction], direction, am, sig["stop_" + direction], sig["tgt_" + direction],
                    sig["exit_" + direction]))


# ---------------------------------------------------------------- sizing family (B-744, B-745)
POLICIES = ("fixed2pct", "optf_capped2pct", "optf_uncapped", "halff", "martingale_control")


def best_f(R, grid=None):
    grid = np.arange(0.01, 0.51, 0.01) if grid is None else grid
    R = np.asarray(R, float)
    worst = max(1e-9, -R.min()) if len(R) else 1.0
    best, bg = 0.01, -1e9
    for f in grid:
        w = 1 + f * R / worst
        if (w <= 0).any():
            continue
        g = np.log(w).sum()
        if g > bg:
            best, bg = f, g
    return best, worst


def run_account(R, policy, f_opt=0.01, worst=1.0):
    """R: per-trade net R-multiples (stop = -1R). Returns (final_equity, max_drawdown)."""
    eq, peak, mdd, loss_streak = 1.0, 1.0, 0.0, 0
    for r in R:
        if policy == "fixed2pct":
            risk = 0.02
        elif policy == "optf_capped2pct":
            risk = min(0.02, f_opt)
        elif policy == "optf_uncapped":
            risk = f_opt
        elif policy == "halff":
            risk = f_opt / 2
        else:                                                    # martingale: double after each loss, cap 5 doublings
            risk = min(0.01 * 2 ** min(loss_streak, 5), 0.32)
        if policy in ("optf_uncapped", "halff"):                 # Vince f is fraction of the worst loss
            eq *= max(0.0, 1 + risk * r / worst)
        else:
            eq *= max(0.0, 1 + risk * r)
        loss_streak = loss_streak + 1 if r < 0 else 0
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak if peak > 0 else 1.0)
        if eq <= 0:
            return 0.0, 1.0
    return eq, mdd


def run_sizing_symbol(df, tf, aggs):
    sig = er.v_ema13(df)
    sf = 2.0 * float((er.atr(df) / df["Close"]).median())
    if not sf > 0:
        return
    for direction in ("long", "short"):
        tr = er.simulate(df, sig, direction, 2.0)
        if len(tr) < 12:
            continue
        R = np.array([t["ret"] / sf for t in tr])
        k = len(R) // 2
        f_opt, worst = best_f(R[:k])                              # fit on first half, trade second half
        for pol in POLICIES:
            eq, mdd = run_account(R[k:], pol, f_opt, worst)
            tag = er.make_tag("sizing", pol, direction, tf, {"atr": 2.0})
            a = aggs.setdefault("sizing::" + tag, {"n_acct": 0, "sum_log_final": 0.0, "dd_gt50": 0,
                                                   "sum_dd": 0.0, "ruined": 0, "n_trades": 0})
            a["n_acct"] += 1
            a["n_trades"] += len(R) - k
            a["sum_log_final"] += float(np.log(max(eq, 1e-6)))
            a["sum_dd"] += mdd
            a["dd_gt50"] += int(mdd > 0.5)
            a["ruined"] += int(eq < 0.2)


# ---------------------------------------------------------------- breadth family
def breadth_accumulate(df, state, topk=15):
    """Fold one symbol's daily bars into the shard's per-date partial sums."""
    c, v = df["Close"], df["Volume"]
    ret = c.diff()
    adv, dec = (ret > 0).astype(float), (ret < 0).astype(float)
    nh = (c >= c.shift(1).rolling(252, min_periods=200).max()).astype(float)
    nl = (c <= c.shift(1).rolling(252, min_periods=200).min()).astype(float)
    nft = np.sign(er.obv(df).diff(5)).fillna(0.0)
    cols = {"adv": adv, "dec": dec, "advvol": adv * v, "decvol": dec * v, "nh": nh, "nl": nl, "nft": nft}
    tab = state.setdefault("sums", {})
    for dt, i in zip(df.index.strftime("%Y-%m-%d"), range(len(df))):
        row = tab.setdefault(dt, {k: 0.0 for k in cols})
        for k, s in cols.items():
            row[k] += float(s.iloc[i])
    top = state.setdefault("top", {})
    vv = v.to_numpy()
    sg = np.sign(ret.fillna(0).to_numpy())
    for dt, i in zip(df.index.strftime("%Y-%m-%d"), range(len(df))):
        h = top.setdefault(dt, [])
        item = (float(vv[i]), float(sg[i]))
        if len(h) < topk:
            heapq.heappush(h, item)
        elif item > h[0]:
            heapq.heapreplace(h, item)


def breadth_merge_states(states, topk=15):
    sums, top = {}, {}
    for st in states:
        for dt, row in st["sums"].items():
            t = sums.setdefault(dt, {k: 0.0 for k in row})
            for k, x in row.items():
                t[k] += x
        for dt, items in st["top"].items():
            h = top.setdefault(dt, [])
            for it in items:
                it = tuple(it)
                if len(h) < topk:
                    heapq.heappush(h, it)
                elif it > h[0]:
                    heapq.heapreplace(h, it)
    df = pd.DataFrame.from_dict(sums, orient="index").sort_index()
    df.index = pd.to_datetime(df.index)
    df["mas"] = [sum(s for _, s in top.get(d.strftime("%Y-%m-%d"), [])) for d in df.index]
    return df.iloc[1:]


def breadth_signals(idx, bd):
    """idx: index OHLCV (^NSEI); bd: merged breadth frame. -> {rule_variant: (params, long, short)}."""
    c = idx["Close"]
    bd = bd.reindex(idx.index).ffill()
    hi50, lo50 = c >= c.shift(1).rolling(50).max(), c <= c.shift(1).rolling(50).min()
    ad = (bd["adv"] - bd["dec"]).cumsum()
    nhnl = bd["nh"] - bd["nl"]
    trin = (bd["adv"] / bd["dec"].replace(0, np.nan)) / (bd["advvol"] / bd["decvol"].replace(0, np.nan))
    t13 = er.ema(trin.ffill(), 13)
    bull = c > er.ema(c, 200)
    out = {}
    adhi = ad >= ad.shift(1).rolling(50).max()
    adlo = ad <= ad.shift(1).rolling(50).min()
    out["ad_confirm"] = ({}, edge(hi50 & adhi), edge(lo50 & adlo))
    out["ad_diverge"] = ({}, edge(lo50 & ~adlo), edge(hi50 & ~adhi))
    nm = nhnl.rolling(10).mean()
    neg60, pos60 = (nm < 0).rolling(60).min() > 0, (nm > 0).rolling(60).min() > 0
    out["nhnl_turn"] = ({}, edge((nm > 0) & neg60.shift(1, fill_value=False)), edge((nm < 0) & pos60.shift(1, fill_value=False)))
    out["nhnl_diverge"] = ({}, edge(lo50 & (nhnl > nhnl.shift(1).rolling(50).min())),
                           edge(hi50 & (nhnl < nhnl.shift(1).rolling(50).max() * 0.5)))
    for reg, os_, ob in (("bull", 0.95, 0.67), ("bear", 1.05, 0.72)):
        m = bull if reg == "bull" else ~bull
        lg = (t13.shift(1) > os_) & (t13 <= os_) & m
        sh = (t13.shift(1) < ob) & (t13 >= ob) & m
        out["trin13_" + reg] = ({"os": os_, "ob": ob}, edge(lg), edge(sh))
    lo20, hi20 = c <= c.shift(1).rolling(20).min(), c >= c.shift(1).rolling(20).max()
    out["nhnl_trin_combo"] = ({}, edge((t13 > 0.95) & lo20 & (nhnl > nhnl.shift(1).rolling(20).min())),
                              edge((t13 < 0.70) & hi20 & (nhnl < nhnl.shift(1).rolling(20).max())))
    clim = bd["nft"]
    chi, clo = clim >= clim.shift(1).rolling(50).max(), clim <= clim.shift(1).rolling(50).min()
    out["climax"] = ({}, edge(hi50 & chi), edge(hi50 & ~chi))
    mas = bd["mas"].cumsum()
    mhi, mlo = mas >= mas.shift(1).rolling(50).max(), mas <= mas.shift(1).rolling(50).min()
    out["mas_diverge"] = ({}, edge(lo50 & ~mlo), edge(hi50 & ~mhi))
    return out


def breadth_trade(idx, bd, tf="1d"):
    aggs = {}
    for rule, (params, lg, sh) in breadth_signals(idx, bd).items():
        sig = {"long": B(lg), "short": B(sh)}
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                tag = er.make_tag("breadth", rule, direction, tf, {**params, "atr": am})
                er.add_trades(aggs.setdefault(tag, er.new_agg()), sim2(idx, sig[direction], direction, am))
    return aggs


# ---------------------------------------------------------------- driver
def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, bstate, fetched = {}, {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            df = er.prep(raw)
            fetched += 1
            if args.family == "sizing":
                run_sizing_symbol(df, args.interval, aggs)
            elif args.family == "breadth":
                breadth_accumulate(df, bstate)
            else:
                run_symbol(df, args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched, "universe": len(syms),
               "aggs": aggs, "breadth": bstate},
              open(os.path.join(args.out, f"b3_{args.family}_{args.shard}.json"), "w"))


def merge_dir(path):
    merged, sizing, bstates, fetched, uni = {}, {}, [], 0, 0
    for f in sorted(glob.glob(os.path.join(path, "**", "b3_*.json"), recursive=True)):
        d = json.load(open(f))
        fetched += d.get("fetched", 0)
        uni += d.get("universe", 0)
        for tag, ag in d["aggs"].items():
            if tag.startswith("sizing::"):
                t = sizing.setdefault(tag[8:], {k: 0 for k in ag})
                for k, x in ag.items():
                    t[k] += x
            else:
                er.merge_aggs(merged.setdefault(tag, er.new_agg()), ag)
        if d.get("breadth"):
            bstates.append(d["breadth"])
    if bstates:
        try:
            sys.path.insert(0, ".")
            import main as m
            raw = m.fetch_ohlc("^NSEI", "5y", "1d")
            idx = er.prep(raw)
            for tag, ag in breadth_trade(idx, breadth_merge_states(bstates)).items():
                er.merge_aggs(merged.setdefault(tag, er.new_agg()), ag)
        except Exception as ex:
            print("BREADTH MERGE ERROR", ex, file=sys.stderr)
    rows = [{"tag": t, **er.summarize(a)} for t, a in merged.items()]
    rows.sort(key=lambda r: (r["pfnet"] is None, -(r["pfnet"] or 0)))
    srows = []
    for t, a in sorted(sizing.items()):
        n = max(1, a["n_acct"])
        srows.append({"tag": t, "accounts": a["n_acct"], "trades": a["n_trades"],
                      "geo_mean_final_equity": round(float(np.exp(a["sum_log_final"] / n)), 4),
                      "mean_max_drawdown_pct": round(100 * a["sum_dd"] / n, 2),
                      "pct_accounts_dd_over_50": round(100 * a["dd_gt50"] / n, 2),
                      "pct_accounts_ruined": round(100 * a["ruined"] / n, 2)})
    return {"symbols_fetched": fetched, "universe": uni, "cost_round_trip": COST, "rows": rows, "sizing_rows": srows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=FAMILIES)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.merge:
        res = merge_dir(args.merge)
        print(f"symbols fetched (sum over families): {res['symbols_fetched']} of universe slots {res['universe']}")
        print(f"{'tag':96s} {'n':>7s} {'PFnet':>7s} {'PFgross':>8s} {'win%':>6s} {'hold':>5s}  exits")
        for r in res["rows"]:
            print(f"{r['tag']:96s} {r['n']:7d} {str(r['pfnet']):>7s} {str(r['pf_gross']):>8s} "
                  f"{r['win_pct']:6.1f} {r['avg_hold_bars']:5.1f}  {r['exit_reasons']}")
        for r in res["sizing_rows"]:
            print("SIZING", r)
        if args.json:
            json.dump(res, open(args.json, "w"), indent=1)
        return 0
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
