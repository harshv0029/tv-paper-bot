#!/usr/bin/env python3
"""Elder trend / regime / MA-system / context research (backlog B-567, B-570, B-580, B-581,
B-586, B-587, B-593, B-598, B-599, B-628, B-629, B-630, B-631, B-632, B-633). Research only.

Same simulator, cost model and rules as scripts/elder_indicators_research.py (stop on every
trade, ATR 1.5/2/3, 0.8% round trip, next-bar-open entry, 30-bar max hold, BOTH directions via
the reciprocal-price mirror, full universe via main._load_nse_universe_from_file(), daily bars;
--interval/--period re-run other candle sizes - bar-count constants change meaning, 4h owed).

Families (one workflow job each):
  ma      B-630 mechanical 4-step MA system (EMA 13/21/26 x plain) | B-629 whipsaw filters
          (close beyond MA twice, penetration margin 0.5/1.0 ATR) | B-631 Donchian 4/9/18-day
          MA triple (all three turn the same way)
  regime  B-580 flat-EMA filter (no new EMA high/low in 21 bars = stand aside) on ema13 dips
          | B-581 trend-vs-range switch (ADX>thr -> EMA-dip trend method; else Stochastic
          oscillator) | B-632 ensemble vote (EMA slope, MACD>0, +DI>-DI; need 2 or 3, plus
          oscillator veto) | B-567 never-buck-the-trend (weekly-gated vs against-trend CONTROL)
          | B-628 weekly-trend alignment of daily 20-bar breakouts (aligned vs counter control)
          | B-570 trade-less-often (signal cooldown 0/5/10/20 bars)
  osc     B-586 MACD-H triple divergence | B-587 3-month (63-bar) MACD-H record confirm
          | B-593 ADX soft-exit (ADX falling = exit ema13-dip trades) | B-633 RSI trendline break
          (RSI(14) pivot-high line breakout leads price) | B-598 gap confirmation time-stop
          (exit after N bars with no new extreme) | B-599 opening-gap fade (gap vs prior close)

Usage:
  python3 scripts/elder_trend_context_research.py --family ma --shard 0 --nshards 4 --out out/
  python3 scripts/elder_trend_context_research.py --merge out/ --json merged.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import b5_merge  # noqa: E402
from elder_patterns_research import both, flip, pivots, _exit_ema  # noqa: E402

FAMILIES = ("ma", "regime", "osc")


def rsi(c, n=14):
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def weekly_up(df):
    """Weekly EMA13 slope sign mapped to daily bars from COMPLETED weeks only (no look-ahead)."""
    wk = df["Close"].resample("W-FRI").last().dropna()
    s = np.sign(er.ema(wk, 13).diff()).shift(1)
    return s.reindex(df.index, method="ffill") > 0


# ------------------------------------------------------------------ ma family
def d_ma_system(df, n=13, confirm=1, margin=0.0):
    """Long: MA rising and close above MA (confirm closes in a row, margin in ATR beyond MA);
    exit when close < MA (4-step baseline: buy rise+above, exit below)."""
    c = df["Close"]
    e = er.ema(c, n)
    a = er.atr(df)
    above = c > e + margin * a
    ok = above.copy()
    for k in range(1, confirm):
        ok = ok & above.shift(k, fill_value=False)
    ent = ok & (e > e.shift(1)) & ~(ok.shift(1, fill_value=False))
    return ent, (c < e)


def d_donchian_triple(df):
    c = df["Close"]
    m4, m9, m18 = (c.rolling(k).mean() for k in (4, 9, 18))
    all_up = (m4 > m4.shift(1)) & (m9 > m9.shift(1)) & (m18 > m18.shift(1))
    ent = all_up & ~all_up.shift(1, fill_value=False)
    ex = (m9 < m9.shift(1))
    return ent, ex


# ------------------------------------------------------------------ regime family
def _dip(df, n=13):
    e = er.ema(df["Close"], n)
    up = e > e.shift(1)
    return up & (df["Low"] <= e) & (df["Close"] > e * 0.985), e, up


def d_flat_filter(df, flat=21, on=True):
    ent, e, up = _dip(df)
    if on:
        new_hi = e >= e.rolling(flat).max()
        new_lo = e <= e.rolling(flat).min()
        trending = new_hi.rolling(flat).max().astype(bool) | new_lo.rolling(flat).max().astype(bool)
        ent = ent & trending
    return ent, (~up & (df["Close"] < e))


def d_regime_switch(df, thr=20, osc="stoch"):
    adx, p, m = er.adx_di(df)
    ent_tr, e, up = _dip(df)
    st = er.stochastic(df, 5, 3)
    range_ent = (st < 20) & (st > st.shift(1))
    ent = ((adx > thr) & ent_tr) | ((adx <= thr) & range_ent)
    ex = ((adx > thr) & ~up & (df["Close"] < e)) | ((adx <= thr) & (st > 70))
    return ent, ex


def d_ensemble(df, need=2, veto=True):
    c = df["Close"]
    e = er.ema(c, 13)
    macd = er.ema(c, 12) - er.ema(c, 26)
    _, p, m = er.adx_di(df)
    votes = (e > e.shift(1)).astype(int) + (macd > 0).astype(int) + (p > m).astype(int)
    st = er.stochastic(df, 5, 3)
    ent = (votes >= need) & (votes.shift(1) < need) & ((st < 80) if veto else True)
    return ent, (votes < 2)


def d_never_buck(df, mode="gated"):
    ent, e, up = _dip(df)
    wk = weekly_up(df)
    ent = ent & (wk if mode == "gated" else ~wk)       # "against" = negative control
    return ent, (~up & (df["Close"] < e))


def d_wk_align(df, mode="aligned"):
    c, h = df["Close"], df["High"]
    brk = c > h.shift(1).rolling(20).max()
    wk = weekly_up(df)
    return brk & (wk if mode == "aligned" else ~wk), _exit_ema(df)


def d_cooldown(df, gap=0):
    ent, e, up = _dip(df)
    if gap:
        a = ent.to_numpy().copy()
        last = -10 ** 9
        for i in np.flatnonzero(a):
            if i - last < gap:
                a[i] = False
            else:
                last = i
        ent = pd.Series(a, index=df.index)
    return ent, (~up & (df["Close"] < e))


# ------------------------------------------------------------------ osc family
def d_macdh_triple(df, w=3):
    c = df["Close"].to_numpy(float)
    h = er.macd_hist(df["Close"]).to_numpy()
    n = len(c)
    ent = np.zeros(n, bool)
    piv = []                                        # (idx, price, hist) of pivot lows with h<0
    for i, conf in pivots(c, w, high=False):
        if np.isnan(h[i]) or h[i] >= 0:
            continue
        piv.append((i, c[i], h[i]))
        if len(piv) >= 3:
            (_, p1, h1), (_, p2, h2), (_, p3, h3) = piv[-3:]
            if p3 < p2 < p1 and h3 > h2 > h1 and conf < n:
                ent[conf] = True
    return ent, _exit_ema(df).to_numpy()


def d_macdh_record(df, look=63):
    h = er.macd_hist(df["Close"])
    rec = h >= h.shift(1).rolling(look).max()
    c = df["Close"]
    ent = rec & (c > c.shift(1).rolling(look).max() * 0.97) & ~rec.shift(1, fill_value=False)
    return ent, (h < h.shift(1)) & (h < 0)


def d_adx_softexit(df, mode="soft"):
    ent, e, up = _dip(df)
    adx, p, m = er.adx_di(df)
    ex = (~up & (df["Close"] < e))
    if mode == "soft":
        ex = ex | ((adx < adx.shift(1)) & (adx.shift(1) < adx.shift(2)) & (df["Close"] < e))
    return ent, ex


def d_rsi_tl(df, w=3):
    r = rsi(df["Close"]).to_numpy()
    n = len(r)
    ent = np.zeros(n, bool)
    ph = pivots(np.nan_to_num(r, nan=0.0), w, True)
    for k in range(1, len(ph)):
        (i1, _), (i2, c2) = ph[k - 1], ph[k]
        if r[i2] >= r[i1] or i2 - i1 < 3:
            continue
        sl = (r[i2] - r[i1]) / (i2 - i1)
        nxt = ph[k + 1][0] if k + 1 < len(ph) else n
        for j in range(c2, min(n, nxt + 1, c2 + 30)):
            if r[j] > r[i2] + sl * (j - i2):
                ent[j] = True
                break
    return ent, _exit_ema(df).to_numpy()


def d_gap_timestop(df, nb=3):
    """Breakaway-style gap up on volume; exit if no new high within nb bars of the gap."""
    h, l, c, v = (df[k] for k in ("High", "Low", "Close", "Volume"))
    gap = (l > h.shift(1)) & (v >= 1.5 * v.shift(1).rolling(5).mean())
    ex = gap.shift(nb, fill_value=False) & (h.rolling(nb).max() <= h.shift(nb))
    return gap, ex


def d_open_gap_fade(df, thr=0.01):
    """Index-futures style opening-gap fade applied to stocks: LONG after a gap DOWN > thr that
    closes its day above the open (first-bar reclaim); the mirror fades gap-ups."""
    o, c = df["Open"], df["Close"]
    gap = o / c.shift(1) - 1
    ent = (gap < -thr) & (c > o)
    return ent, (c > c.shift(1)) | (df["High"] < df["High"].shift(1))


def variant_specs(family):
    S = []
    if family == "ma":
        for n in (13, 21, 26):
            S.append(("ma4step", {"n": n, "cf": 1, "mg": 0}, both(lambda d, n=n: d_ma_system(d, n, 1, 0.0)), {}))
        for cf in (2,):
            S.append(("ma_whipsaw_close", {"n": 13, "cf": cf, "mg": 0}, both(lambda d, c=cf: d_ma_system(d, 13, c, 0.0)), {}))
        for mg in (0.5, 1.0):
            S.append(("ma_whipsaw_margin", {"n": 13, "cf": 1, "mg": mg}, both(lambda d, g=mg: d_ma_system(d, 13, 1, g)), {}))
        S.append(("donchian_triple", {"k": 4918}, both(d_donchian_triple), {}))
    elif family == "regime":
        S.append(("flat_off", {"fl": 0}, both(lambda d: d_flat_filter(d, 21, False)), {"be": "ema"}))
        S.append(("flat_on", {"fl": 21}, both(lambda d: d_flat_filter(d, 21, True)), {"be": "ema"}))
        for thr in (15, 20, 25):
            S.append(("trend_range_switch", {"thr": thr}, both(lambda d, t=thr: d_regime_switch(d, t)), {}))
        for need in (2, 3):
            for veto in (0, 1):
                S.append(("ensemble", {"need": need, "veto": veto}, both(lambda d, n=need, v=veto: d_ensemble(d, n, bool(v))), {}))
        for mode in ("gated", "against"):
            S.append((f"never_buck_{mode}", {"wk": 13}, both(lambda d, m=mode: d_never_buck(d, m)), {}))
        for mode in ("aligned", "counter"):
            S.append((f"wk_align_{mode}", {"wk": 13}, both(lambda d, m=mode: d_wk_align(d, m)), {}))
        for gap in (0, 5, 10, 20):
            S.append(("cooldown", {"gap": gap}, both(lambda d, g=gap: d_cooldown(d, g)), {}))
    elif family == "osc":
        S.append(("macdh_triple_div", {"w": 3}, both(d_macdh_triple), {}))
        S.append(("macdh_record63", {"lb": 63}, both(d_macdh_record), {}))
        for mode in ("hard", "soft"):
            S.append((f"adx_exit_{mode}", {"n": 14}, both(lambda d, m=mode: d_adx_softexit(d, m)), {"be": "ema"}))
        S.append(("rsi_tl_break", {"w": 3}, both(d_rsi_tl), {}))
        for nb in (2, 3, 5):
            S.append(("gap_timestop", {"nb": nb}, both(lambda d, nb=nb: d_gap_timestop(d, nb)), {}))
        for thr in (0.005, 0.01, 0.02):
            S.append(("open_gap_fade", {"thr": thr}, both(lambda d, t=thr: d_open_gap_fade(d, t)), {}))
    else:
        raise ValueError(family)
    return S


def run_symbol(df, family, tf, aggs):
    for variant, params, fn, mgmt in variant_specs(family):
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
                er.add_trades(aggs.setdefault(tag, er.new_agg()), er.simulate(df, sig, direction, am, mgmt))


def _main_shard(args):
    sys.path.insert(0, ".")
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % args.nshards == args.shard]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, args.period, args.interval)
            if raw is None or len(raw) < 120:
                continue
            fetched += 1
            run_symbol(er.prep(raw), args.family, args.interval, aggs)
        except Exception as ex:
            print("ERROR", s, ex, file=sys.stderr)
    print(f"{args.family} shard {args.shard}: fetched {fetched}/{len(syms)}, variants {len(aggs)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump({"family": args.family, "interval": args.interval, "fetched": fetched, "universe": len(syms),
               "aggs": aggs}, open(os.path.join(args.out, f"{args.family}_{args.shard}.json"), "w"))


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
        return b5_merge.merge_main(args.merge, args.json)
    if not args.family:
        ap.error("--family or --merge required")
    _main_shard(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
