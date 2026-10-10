"""Pattern lab (B-81..B-206 batch): ~90 price-only rules from the research books,
each tested BOTH directions x hold x ATR-stop on the full NSE universe at one candle size.

Signal at the close of bar t -> entry next open -> exit after H bars at the close, or at
a fixed ATR(14) stop on the bar's low/high (k=0: no stop). Per symbol a cell is
non-overlapping. Net of main.ROUND_TRIP_COST_PCT. Each (rule, dir, tf, hold, atr) is
its own tag: <family>__<variant>__<dir>__<tf>__atr<k>_h<H>__v1 (never pooled).
Env: TF (1d|1h|15m|5m), UNI (n200 = live swing watchlist only), MAXSYM (debug cap).
Output docs/pattern_lab_results[_tf][_n200].json: {tag: {pfnet, win_pct, n, avg_net_pct, avg_held_bars}}.
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

TF = os.environ.get("TF", "1d")
UNI = os.environ.get("UNI", "")
PERIOD = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}[TF]
PER_DAY = {"1d": 1, "1h": 6, "15m": 25, "5m": 75}[TF]
HOLDS = (3, 5, 10, 20) if TF == "1d" else (PER_DAY, 3 * PER_DAY, 5 * PER_DAY)
KS = (0, 2.5)
OUT = os.path.join(ROOT, "docs", "pattern_lab_results" + ("" if TF == "1d" else f"_{TF}") + ("_n200" if UNI == "n200" else "") + ".json")


# ---------- helpers ----------
def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def shift(x, k=1):
    out = np.full_like(x, np.nan, dtype=float)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:k] = x[-k:]
    return out


def atr_arr(h, l, c, n=14):
    pc = shift(c)
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def cross_up(a, b):
    return (a > b) & (shift(a) <= shift(b))


def cross_dn(a, b):
    return (a < b) & (shift(a) >= shift(b))


def rolling_max(x, n):
    return pd.Series(x).rolling(n).max().to_numpy()


def rolling_min(x, n):
    return pd.Series(x).rolling(n).min().to_numpy()


# ---------- rules: f(o,h,l,c,v) -> (long_bool, short_bool) ----------
def _ctx(o, h, l, c):
    body = np.abs(c - o)
    rng = np.maximum(h - l, 1e-9)
    up = c > o
    dn = c < o
    ma10 = sma(c, 10)
    return body, rng, up, dn, ma10


def r_doji_family(o, h, l, c, v):
    body, rng, up, dn, ma10 = _ctx(o, h, l, c)
    doji = body <= 0.1 * rng
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    grave = doji & (upper >= 0.6 * rng) & (lower <= 0.1 * rng)
    dragon = doji & (lower >= 0.6 * rng) & (upper <= 0.1 * rng)
    longleg = doji & (upper >= 0.3 * rng) & (lower >= 0.3 * rng)
    return {"dragonfly": (dragon, grave), "gravestone": (np.zeros_like(grave), grave),
            "longleg_trend": (longleg & (c < ma10), longleg & (c > ma10))}


def r_hammer_family(o, h, l, c, v):
    body, rng, up, dn, ma10 = _ctx(o, h, l, c)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    small = body <= 0.35 * rng
    hammer_shape = small & (lower >= 2 * body) & (upper <= 0.15 * rng)
    star_shape = small & (upper >= 2 * body) & (lower <= 0.15 * rng)
    down = c < ma10
    upt = c > ma10
    return {
        "hammer_hanging": (hammer_shape & down, hammer_shape & upt),
        "invhammer_shootstar": (star_shape & down, star_shape & upt),
    }


def r_engulf_harami(o, h, l, c, v):
    body, rng, up, dn, ma10 = _ctx(o, h, l, c)
    po, pc_ = shift(o), shift(c)
    bull_eng = up & (po > pc_) & (c >= po) & (o <= pc_)
    bear_eng = dn & (po < pc_) & (c <= po) & (o >= pc_)
    bull_har = up & (po > pc_) & (c <= po) & (o >= pc_) & (body < np.abs(po - pc_))
    bear_har = dn & (po < pc_) & (c >= po) & (o <= pc_) & (body < np.abs(po - pc_))
    return {"engulfing": (bull_eng, bear_eng), "harami": (bull_har, bear_har),
            "engulfing_ma10": (bull_eng & (c < ma10), bear_eng & (c > ma10)),
            "harami_ma10": (bull_har & (c < ma10), bear_har & (c > ma10))}


def r_piercing_cloud(o, h, l, c, v):
    po, pc_, ph, pl = shift(o), shift(c), shift(h), shift(l)
    mid = (po + pc_) / 2
    pierce = (pc_ < po) & (c > o) & (o < pl) & (c > mid) & (c < po)
    cloud = (pc_ > po) & (c < o) & (o > ph) & (c < mid) & (c > po)
    return {"piercing_cloud": (pierce, cloud)}


def r_stars(o, h, l, c, v):
    body, rng, up, dn, ma10 = _ctx(o, h, l, c)
    o2, c2, o1, c1 = shift(o, 2), shift(c, 2), shift(o), shift(c)
    small1 = np.abs(c1 - o1) <= 0.3 * np.abs(c2 - o2)
    morning = (c2 < o2) & small1 & (np.maximum(o1, c1) < c2) & up & (c > (o2 + c2) / 2)
    evening = (c2 > o2) & small1 & (np.minimum(o1, c1) > c2) & dn & (c < (o2 + c2) / 2)
    doji1 = np.abs(c1 - o1) <= 0.1 * np.maximum(shift(h) - shift(l), 1e-9)
    mdoji = (c2 < o2) & doji1 & up & (c > (o2 + c2) / 2)
    edoji = (c2 > o2) & doji1 & dn & (c < (o2 + c2) / 2)
    return {"morning_evening_star": (morning, evening), "star_doji": (mdoji, edoji)}


def r_three_bar(o, h, l, c, v):
    o1, c1, o2, c2 = shift(o), shift(c), shift(o, 2), shift(c, 2)
    soldiers = (c > o) & (c1 > o1) & (c2 > o2) & (c > c1) & (c1 > c2)
    crows = (c < o) & (c1 < o1) & (c2 < o2) & (c < c1) & (c1 < c2)
    in_up = (c2 < o2) & (c1 > o1) & (c1 < o2) & (c > o) & (c > o2)
    in_dn = (c2 > o2) & (c1 < o1) & (c1 > o2) & (c < o) & (c < o2)
    out_up = (c2 < o2) & (c1 > o1) & (c1 > o2) & (o1 < c2) & (c > c1)
    out_dn = (c2 > o2) & (c1 < o1) & (c1 < o2) & (o1 > c2) & (c < c1)
    return {"soldiers_crows": (soldiers, crows), "three_inside": (in_up, in_dn), "three_outside": (out_up, out_dn)}


def r_misc_candles(o, h, l, c, v):
    body, rng, up, dn, ma10 = _ctx(o, h, l, c)
    po, pc_, ph, pl = shift(o), shift(c), shift(h), shift(l)
    belt_up = up & (o <= l + 0.02 * rng) & (body >= 0.7 * rng)
    belt_dn = dn & (o >= h - 0.02 * rng) & (body >= 0.7 * rng)
    kick_up = (pc_ < po) & (o > po) & up
    kick_dn = (pc_ > po) & (o < po) & dn
    match_low = (pc_ < po) & dn & (np.abs(c - pc_) <= 0.003 * c)
    match_high = (pc_ > po) & up & (np.abs(c - pc_) <= 0.003 * c)
    sep_up = (pc_ < po) & up & (np.abs(o - po) <= 0.003 * o) & (c > o)
    sep_dn = (pc_ > po) & dn & (np.abs(o - po) <= 0.003 * o) & (c < o)
    tasuki_up = (shift(c, 2) > shift(o, 2)) & (po > shift(h, 2)) & (pc_ > po) & dn & (o < pc_) & (o > po) & (c < po) & (c > shift(h, 2))
    tasuki_dn = (shift(c, 2) < shift(o, 2)) & (po < shift(l, 2)) & (pc_ < po) & up & (o > pc_) & (o < po) & (c > po) & (c < shift(l, 2))
    # rising/falling three methods (5 bars)
    c4, o4 = shift(c, 4), shift(o, 4)
    rising3 = (c4 > o4) & (shift(h, 3) < shift(h, 4)) & (shift(l, 1) > shift(l, 4)) & up & (c > shift(h, 4))
    falling3 = (c4 < o4) & (shift(l, 3) > shift(l, 4)) & (shift(h, 1) < shift(h, 4)) & dn & (c < shift(l, 4))
    return {"belt_hold": (belt_up & (c < ma10), belt_dn & (c > ma10)), "kicking": (kick_up, kick_dn),
            "matching_low_high": (match_low & (c < ma10), match_high & (c > ma10)),
            "separating_lines": (sep_up, sep_dn), "tasuki_gap": (tasuki_up, tasuki_dn),
            "three_methods": (rising3, falling3)}


def r_key_reversal_gaps(o, h, l, c, v):
    ph, pl, pc_ = shift(h), shift(l), shift(c)
    key_up = (l < pl) & (c > pc_)
    key_dn = (h > ph) & (c < pc_)
    gap_up = o > ph * 1.01
    gap_dn = o < pl * 0.99
    ma50 = sma(c, 50)
    runaway = (gap_up & (c > ma50) & (c > o), gap_dn & (c < ma50) & (c < o))
    island_long = gap_dn & False
    exhaustion = (gap_up & (c < o) & (c > ma50), gap_dn & (c > o) & (c < ma50))  # gap that fails: fade it
    return {"key_reversal": (key_up, key_dn), "gap_runaway": runaway,
            "gap_exhaustion_fade": (exhaustion[1], exhaustion[0])}


def r_psar(o, h, l, c, v):
    n = len(c)
    sar = np.full(n, np.nan)
    trend = np.zeros(n)
    if n < 10:
        return {"psar_flip": (np.zeros(n, bool), np.zeros(n, bool))}
    up = True
    af, step, mx = 0.02, 0.02, 0.2
    ep = h[0]
    s = l[0]
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                up, s, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, mx)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                up, s, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, mx)
        sar[i] = s
        trend[i] = 1 if up else -1
    flip_up = (trend == 1) & (shift(trend) == -1)
    flip_dn = (trend == -1) & (shift(trend) == 1)
    di_pos, di_neg = _di(h, l, c)
    return {"psar_flip": (flip_up, flip_dn), "psar_flip_di": (flip_up & (di_pos > di_neg), flip_dn & (di_neg > di_pos))}


def _di(h, l, c, n=14):
    up = h - shift(h)
    dn = shift(l) - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr_arr(h, l, c, n)
    return (100 * pd.Series(pdm).rolling(n).mean().to_numpy() / a, 100 * pd.Series(ndm).rolling(n).mean().to_numpy() / a)


def r_donchian_cycle(o, h, l, c, v):
    out = {}
    for n, name in ((10, "2wk"), (20, "4wk"), (40, "8wk")):
        hi, lo = shift(rolling_max(h, n)), shift(rolling_min(l, n))
        out[f"donchian_{name}_break"] = (c > hi, c < lo)
        out[f"donchian_{name}_fade"] = (c <= lo, c >= hi)  # cycle low buy / cycle high sell
    return out


def r_ma_systems(o, h, l, c, v):
    s4, s9, s18 = sma(c, 4), sma(c, 9), sma(c, 18)
    aligned_up = (s4 > s9) & (s9 > s18)
    aligned_dn = (s4 < s9) & (s9 < s18)
    e9, e21 = ema(c, 9), ema(c, 21)
    # kaufman AMA
    er_n = 10
    chg = np.abs(c - shift(c, er_n))
    vol = pd.Series(np.abs(c - shift(c))).rolling(er_n).sum().to_numpy()
    er = chg / np.maximum(vol, 1e-9)
    sc = (er * (2 / 3 - 2 / 31) + 2 / 31) ** 2
    ama = np.copy(c)
    for i in range(1, len(c)):
        if not np.isnan(sc[i]):
            ama[i] = ama[i - 1] + sc[i] * (c[i] - ama[i - 1])
    w = np.arange(1, 22)
    lwma = pd.Series(c).rolling(21).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).to_numpy()
    return {"ma_4_9_18_align": (aligned_up & (shift(aligned_up.astype(float)) == 0), aligned_dn & (shift(aligned_dn.astype(float)) == 0)),
            "ema_9_21_cross": (cross_up(e9, e21), cross_dn(e9, e21)),
            "kama_cross": (cross_up(c, ama), cross_dn(c, ama)),
            "lwma21_cross": (cross_up(c, lwma), cross_dn(c, lwma))}


def r_bands(o, h, l, c, v):
    a15, a10 = atr_arr(h, l, c, 15), atr_arr(h, l, c, 10)
    s6 = sma(c, 6)
    e20 = ema(c, 20)
    out = {
        "starc_fade": (c < s6 - 2 * a15, c > s6 + 2 * a15),
        "keltner_raschke_break": (c > e20 + 2 * a10, c < e20 - 2 * a10),
        "keltner_raschke_pullback": ((c > e20) & (l <= e20) & (shift(c) > shift(e20)), (c < e20) & (h >= e20) & (shift(c) < shift(e20))),
    }
    s21 = sma(c, 21)
    for pct in (0.03, 0.05):
        t = str(pct).replace(".", "d")
        out[f"envelope_{t}_fade"] = (c < s21 * (1 - pct), c > s21 * (1 + pct))
        out[f"envelope_{t}_break"] = (c > s21 * (1 + pct), c < s21 * (1 - pct))
    return out


def r_oscillators(o, h, l, c, v):
    tp = (h + l + c) / 3
    ma = sma(tp, 20)
    md = pd.Series(np.abs(tp - ma)).rolling(20).mean().to_numpy()
    cci = (tp - ma) / (0.015 * np.maximum(md, 1e-9))
    hh, ll = rolling_max(h, 14), rolling_min(l, 14)
    wr = -100 * (hh - c) / np.maximum(hh - ll, 1e-9)
    roc = c / shift(c, 12) - 1
    obv = np.cumsum(np.where(c > shift(c), v, np.where(c < shift(c), -v, 0.0)))
    return {
        "cci20_extreme_reversal": (cross_up(cci, np.full_like(cci, -100)), cross_dn(cci, np.full_like(cci, 100))),
        "willr14_extreme_reversal": (cross_up(wr, np.full_like(wr, -80)), cross_dn(wr, np.full_like(wr, -20))),
        "roc12_zero_cross": (cross_up(roc, np.zeros_like(roc)), cross_dn(roc, np.zeros_like(roc))),
        "obv_breakout": (obv > shift(rolling_max(obv, 20)), obv < shift(rolling_min(obv, 20))),
    }


def r_fib_retrace(o, h, l, c, v):
    n = len(c)
    ma50 = sma(c, 50)
    hh, ll = rolling_max(h, 60), rolling_min(l, 60)
    pos = (c - ll) / np.maximum(hh - ll, 1e-9)  # 0 = at swing low, 1 = at swing high
    up_close = c > shift(c)
    dn_close = c < shift(c)
    out = {}
    for name, (lo, hi) in {"fib_382": (0.30, 0.45), "fib_500": (0.45, 0.55), "fib_618": (0.55, 0.70)}.items():
        # uptrend retrace: price sits (1-x) of the way up from the low
        out[name + "_bounce"] = ((c > ma50) & (pos >= 1 - hi) & (pos <= 1 - lo) & up_close,
                                 (c < ma50) & (pos >= lo) & (pos <= hi) & dn_close)
    out["retrace_40_60_trend"] = ((c > ma50) & (pos >= 0.40) & (pos <= 0.60) & up_close & (shift(pos) < pos),
                                   (c < ma50) & (pos >= 0.40) & (pos <= 0.60) & dn_close & (shift(pos) > pos))
    return out


def r_breakout_pullback(o, h, l, c, v):
    hi20, lo20 = shift(rolling_max(h, 20), 1), shift(rolling_min(l, 20), 1)
    brk_up = pd.Series(c > hi20).rolling(8).max().fillna(0).to_numpy().astype(bool)
    brk_dn = pd.Series(c < lo20).rolling(8).max().fillna(0).to_numpy().astype(bool)
    pull_up = brk_up & (l <= hi20 * 1.01) & (c > o) & (c > hi20 * 0.99)
    pull_dn = brk_dn & (h >= lo20 * 0.99) & (c < o) & (c < lo20 * 1.01)
    return {"breakout_pullback": (pull_up & ~(c > hi20), pull_dn & ~(c < lo20)),
            "support_resistance_bounce": ((l <= rolling_min(l, 40) * 1.01) & (c > o), (h >= rolling_max(h, 40) * 0.99) & (c < o))}


def r_four_pct_reversal(o, h, l, c, v):
    n = len(c)
    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    if n < 5:
        return {"four_pct_reversal": (long_sig, short_sig)}
    mode = 0
    ext = c[0]
    for i in range(1, n):
        if mode >= 0:
            ext = max(ext, c[i]) if mode == 1 else min(ext, c[i]) if mode == -1 else ext
        if mode == 0:
            if c[i] >= c[0] * 1.04:
                mode, ext = 1, c[i]
                long_sig[i] = True
            elif c[i] <= c[0] * 0.96:
                mode, ext = -1, c[i]
                short_sig[i] = True
        elif mode == 1:
            ext = max(ext, c[i])
            if c[i] <= ext * 0.96:
                mode, ext = -1, c[i]
                short_sig[i] = True
        else:
            ext = min(ext, c[i])
            if c[i] >= ext * 1.04:
                mode, ext = 1, c[i]
                long_sig[i] = True
    return {"four_pct_reversal": (long_sig, short_sig)}


def r_calendar(o, h, l, c, v, idx=None):
    if idx is None:
        return {}
    m = idx.month
    first = np.zeros(len(idx), bool)
    first[1:] = (m[1:] != m[:-1])
    strong = np.isin(m, (11, 12, 1))
    weak = np.isin(m, (9,))
    return {"month_effect": (first & strong, first & weak)}


def r_volume(o, h, l, c, v):
    avg = sma(v, 20)
    spike = v > 3 * avg
    return {"volume_climax_reversal": (spike & (c < sma(c, 20)) & (c > o), spike & (c > sma(c, 20)) & (c < o)),
            "volume_confirmed_breakout": ((c > shift(rolling_max(h, 20))) & (v > 1.5 * avg), (c < shift(rolling_min(l, 20))) & (v > 1.5 * avg))}


def r_main_atomic(o, h, l, c, v, df=None):
    if df is None:
        return {}
    import main
    out = {}
    for st, pr in (("rsi_reversal", {"rsi_period": 14, "oversold": 30, "overbought": 70}), ("macd_cross", {}),
                   ("bollinger_mean_reversion", {}), ("supertrend", {}), ("stochastic_cross", {})):
        try:
            sig = main.add_strategy_signal(df, st, dict(pr))
            if "short" in sig.columns:
                out[f"main_{st}"] = (sig["long"].fillna(False).to_numpy(bool), sig["short"].fillna(False).to_numpy(bool))
            else:
                out[f"main_{st}"] = (sig["long"].fillna(False).to_numpy(bool), np.zeros(len(df), bool))
        except Exception:
            continue
    return out


def r_pnf(o, h, l, c, v):
    """Point & Figure on closes, 3-box reversal, percent boxes (B-74..B-79 basic signals):
    buy = X column rises above the prior X column top (double-top breakout);
    sell = O column falls below the prior O column bottom (double-bottom breakdown)."""
    out = {}
    n = len(c)
    for pct, name in ((0.01, "box1pct"), (0.02, "box2pct")):
        lg = np.zeros(n, bool)
        sh = np.zeros(n, bool)
        if n < 30:
            out[f"pnf_{name}"] = (lg, sh)
            continue
        step = 1 + pct
        col = 1  # 1 = X (up), -1 = O (down)
        top = bot = c[0]
        prev_top = prev_bot = None
        for i in range(1, n):
            if col == 1:
                if c[i] >= top * step:
                    top = c[i]
                    if prev_top is not None and top > prev_top:
                        lg[i] = True
                elif c[i] <= top / step ** 3:
                    prev_top, col, bot = top, -1, c[i]
            else:
                if c[i] <= bot / step:
                    bot = c[i]
                    if prev_bot is not None and bot < prev_bot:
                        sh[i] = True
                elif c[i] >= bot * step ** 3:
                    prev_bot, col, top = bot, 1, c[i]
        out[f"pnf_{name}"] = (lg, sh)
    return out


def r_lunar(o, h, l, c, v, idx=None):
    """B-112: buy at full moon, sell (short) at new moon. Synodic month 29.530588 d from the
    2000-01-06 new moon; signal on the first bar at/after each phase point."""
    if idx is None:
        return {}
    days = (pd.DatetimeIndex(idx).tz_localize(None).normalize() - pd.Timestamp("2000-01-06")).days.to_numpy()
    phase = (days % 29.530588) / 29.530588
    full = (phase >= 0.5) & (np.roll(phase, 1) < 0.5)
    new = (phase < np.roll(phase, 1))
    full[0] = new[0] = False
    return {"lunar_full_new": (full, new)}


def r_weekly_reversal(o, h, l, c, v, idx=None):
    """B-203: weekly reversal = week makes a new 2-week low and closes above prior week's close (and mirror);
    signalled on the week's last bar. Daily data only."""
    if idx is None or TF != "1d":
        return {}
    s = pd.DataFrame({"h": h, "l": l, "c": c}, index=pd.DatetimeIndex(idx).tz_localize(None))
    wk = s.resample("W").agg({"h": "max", "l": "min", "c": "last"}).dropna()
    up = (wk["l"] < wk["l"].shift()) & (wk["c"] > wk["c"].shift())
    dn = (wk["h"] > wk["h"].shift()) & (wk["c"] < wk["c"].shift())
    last_of_week = s.groupby(s.index.to_period("W")).tail(1).index
    lg = np.zeros(len(c), bool)
    sh = np.zeros(len(c), bool)
    pos = {d: i for i, d in enumerate(s.index)}
    for wend, u, d_ in zip(wk.index, up.to_numpy(), dn.to_numpy()):
        cands = [d for d in last_of_week if d <= wend and (wend - d).days < 7]
        if not cands:
            continue
        i = pos[cands[-1]]
        lg[i] = bool(u)
        sh[i] = bool(d_)
    return {"weekly_reversal": (lg, sh)}


RULE_FUNCS = (r_doji_family, r_hammer_family, r_engulf_harami, r_piercing_cloud, r_stars, r_three_bar, r_misc_candles,
              r_key_reversal_gaps, r_psar, r_donchian_cycle, r_ma_systems, r_bands, r_oscillators, r_fib_retrace,
              r_breakout_pullback, r_four_pct_reversal, r_volume, r_pnf)


def all_signals(df):
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float) if "Volume" in df else np.ones(len(df))
    out = {}
    for fn in RULE_FUNCS:
        try:
            out.update(fn(o, h, l, c, v))
        except Exception as e:
            print("rule fail", fn.__name__, e, flush=True)
    out.update(r_calendar(o, h, l, c, v, idx=df.index))
    out.update(r_lunar(o, h, l, c, v, idx=df.index))
    out.update(r_weekly_reversal(o, h, l, c, v, idx=df.index))
    out.update(r_main_atomic(o, h, l, c, v, df=df))
    return out


def simulate(sig, o, h, l, c, atr, hold, k, cost, side):
    """non-overlapping trades; returns (rets list, held list)"""
    rets, held = [], []
    n = len(c)
    i = 0
    idxs = np.flatnonzero(sig)
    nxt = 0
    for t in idxs:
        if t < nxt or t + 1 >= n or np.isnan(atr[t]):
            continue
        e = t + 1
        ent = o[e]
        if not ent or np.isnan(ent):
            continue
        stop = (ent - k * atr[t]) if side == 1 else (ent + k * atr[t])
        last = min(e + hold - 1, n - 1)
        if last - e + 1 < hold:  # not enough future bars
            continue
        exitp, j_exit = c[last], last
        if k:
            for j in range(e, last + 1):
                if side == 1 and l[j] <= stop:
                    exitp, j_exit = min(stop, o[j]), j
                    break
                if side == -1 and h[j] >= stop:
                    exitp, j_exit = max(stop, o[j]), j
                    break
        r = (exitp / ent - 1) * side - cost
        rets.append(r)
        held.append(j_exit - e + 1)
        nxt = j_exit + 1
    return rets, held


def main_run():
    import yfinance as yf
    import main as app
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    syms = list(app._load_nse_universe_from_file())
    if UNI == "n200":
        w = set(app.SWING_WATCHLIST)
        syms = [s for s in syms if s in w] or list(w)
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    acc = {}
    done = 0
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=PERIOD, interval=TF, group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            if len(df) < 120:
                continue
            o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
            atr = atr_arr(h, l, c)
            sigs = all_signals(df)
            for rule, (lg, sh) in sigs.items():
                for dname, sg, side in (("long", lg, 1), ("short", sh, -1)):
                    sg = np.asarray(sg, bool)
                    if sg.sum() == 0:
                        continue
                    for H in HOLDS:
                        for k in KS:
                            r, hd = simulate(sg, o, h, l, c, atr, H, k, cost, side)
                            if r:
                                a = acc.setdefault((rule, dname, H, k), [[], []])
                                a[0].extend(r)
                                a[1].extend(hd)
            done += 1
        print("batch", b0, "symbols done", done, "cells", len(acc), flush=True)
    res = {}
    for (rule, dname, H, k), (r, hd) in acc.items():
        if len(r) < 30:
            continue
        r = np.array(r)
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        fam, _, var = rule.partition("_")
        ks = "none" if not k else str(k).replace(".", "d")
        tag = f"{rule.split('_')[0]}__{'_'.join(rule.split('_')[1:]) or 'base'}__{dname}__{TF}__atr{ks}_h{H}__v1"
        res[tag] = {"pfnet": round(float(gain / loss), 3) if loss else None, "win_pct": round(float((r > 0).mean() * 100), 1),
                    "n": int(len(r)), "avg_net_pct": round(float(r.mean() * 100), 3), "avg_held_bars": round(float(np.mean(hd)), 2),
                    "bar_hours": {"1d": 6.25, "1h": 1.0, "15m": 0.25, "5m": 5 / 60}[TF]}
    json.dump({"results": res}, open(OUT, "w"), indent=0)
    ok = sorted([(m["pfnet"], m["n"], t) for t, m in res.items() if m["pfnet"] and m["pfnet"] > 1 and m["n"] >= 300], reverse=True)
    print(f"cells={len(res)} viable(PFnet>1,n>=300)={len(ok)}")
    for x in ok[:25]:
        print(x)


if __name__ == "__main__":
    main_run()
