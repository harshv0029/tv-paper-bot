#!/usr/bin/env python3
"""Elder signal-invalidation exit research (backlog B-740): candle sweep and short mirrors on
generic base entries. Research only; no main.py edits.

Elder: decide at entry which signals flagged the trade; exit at once when they disappear instead of
waiting for the stop. The earlier exit-family run (38140914889) tested this only on the OB / VP
long entries, daily bars. This harness runs it on two generic base entries (EMA13 dip, 20-bar
breakout), BOTH directions (true-price short, signals from the reciprocal mirror), on the SAME
candle size as the trade (use --interval 1d / 1h / 15m / 5m; 4h owed, needs a 1h resample).

Invalidation signals (long orientation; the short side runs on the mirror):
  ema   EMA13 no longer rising              (flagged if rising at the signal bar)
  macd  MACD-histogram no longer rising     (flagged if rising at the signal bar)
  ray   opposite Elder-ray signal appears   (Bull Power > 0 and falling while EMA13 falls)
Variants: stoponly (no rule exit) | inval_ema | inval_macd | inval_ray | inval_any (first of the
flagged signals to fail) | inval_all (all flagged signals have failed at once). Stop on EVERY
trade: atr x ATR for atr 1.5/2/3, plus a 6.0 ATR catastrophic stop arm (inval exit is the real
exit there). 30-bar max hold, next-bar-open entry, 0.8% round trip, full universe. The wide-stop
arm for stoponly is the control showing what the invalidation exit adds over a loose stop.
Weekly-timeframe invalidation (the book's weekly EMA13 / weekly MACD-H) was tested on daily bars in
the exit-family run; here the signals are on the trade's own candle.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import elder_lab_driver as drv  # noqa: E402
from douglas_trade_mgmt_research import BASES  # noqa: E402
from elder_patterns_research import flip  # noqa: E402

FAMILIES = ("invalidation",)
ATRS = (1.5, 2.0, 3.0, 6.0)
VARIANTS = ("stoponly", "inval_ema", "inval_macd", "inval_ray", "inval_any", "inval_all")


def valid_flags(df):
    """Long-orientation arrays: valid_{ema,macd} (True while the signal holds) and inval_ray event."""
    e = er.ema(df["Close"], 13)
    rising = e > e.shift(1)
    falling = e < e.shift(1)
    mh = er.macd_hist(df["Close"])
    bull = df["High"] - e
    ray_opp = falling & (bull > 0) & (bull < bull.shift(1))
    f = lambda x: np.asarray(x.fillna(False), bool)   # noqa: E731
    return {"ema": f(rising), "macd": f(mh > mh.shift(1)), "ray_inval": f(ray_opp)}


def flags(df):
    return {"long": valid_flags(df), "short": valid_flags(flip(df))}


def sim(df, sig, fl, direction, am, variant, max_hold=er.MAX_HOLD_BARS, cost=er.COST_ROUND_TRIP):
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    F = fl[direction]
    entry = sig[direction]
    n = len(df)
    trades, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px = o[e]
        if px <= 0:
            continue
        stop = px - d * am * a[s]
        flagged = [k for k in ("ema", "macd") if F[k][s]]
        reason, exit_px, j = None, None, e
        for j in range(e, min(n, e + max_hold + 1)):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                gap = o[j] if j > e else None
                exit_px = stop if gap is None else (min(gap, stop) if d == 1 else max(gap, stop))
                reason = "stop_loss"
                break
            if j > e and variant != "stoponly":
                failed = [k for k in flagged if not F[k][j]]
                ray = bool(F["ray_inval"][j])
                hit = False
                if variant == "inval_ema":
                    hit = "ema" in failed
                elif variant == "inval_macd":
                    hit = "macd" in failed
                elif variant == "inval_ray":
                    hit = ray
                elif variant == "inval_any":
                    hit = bool(failed) or ray
                elif variant == "inval_all":
                    hit = bool(flagged) and len(failed) == len(flagged)
                if hit:
                    exit_px, reason = c[j], "signal_invalidated"
                    break
            if j == e + max_hold:
                exit_px, reason = c[j], "max_hold_timeout"
                break
        if exit_px is None:
            exit_px, reason, j = c[n - 1], "data_end", n - 1
        trades.append({"ret": float(d * (exit_px - px) / px - cost), "hold": int(j - e + 1), "reason": reason})
        free = j
    return trades


def run_symbol(df, family, tf, aggs):
    fl = flags(df)
    for bname, bf in BASES.items():
        try:
            sig = bf(df)
        except Exception as ex:
            print("BASE ERROR", bname, ex, file=sys.stderr)
            continue
        for variant in VARIANTS:
            for direction in ("long", "short"):
                if not sig[direction].any():
                    continue
                for am in ATRS:
                    tag = er.make_tag("elderinval", f"{bname}_{variant}", direction, tf, {"atr": am})
                    tr = sim(df, sig, fl, direction, am, variant)
                    if tr:
                        er.add_trades(aggs.setdefault(tag, er.new_agg()), tr)


def main(argv=None):
    return drv.run(argv, FAMILIES, run_symbol)


if __name__ == "__main__":
    sys.exit(main())
