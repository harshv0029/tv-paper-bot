#!/usr/bin/env python3
"""Elder stop-placement research (backlog B-606). Research only; no main.py edits.

Elder: put the stop beyond the congestion bottom (top for shorts) and at a logical NON-round
level (89.75 not 90). Two families, same two base entry sets (EMA13 dip-buy, 20-bar breakout)
so only the stop changes. Stop on EVERY trade, both directions (true-price short), 0.8% round
trip, next-bar-open entry, 30-bar max hold, EMA13 rule exit, full universe, ATR clamp 1.5/2/3.

  offset  structural stop = lowest low of the last 10 bars (highest high for shorts) pushed
          beyond by k ATR, k in 0.25/0.5/0.75/1.0; distance clamped to the ATR multiple so the
          stop is never wider than atr x ATR (falls back to the raw ATR stop); entry REJECTED
          when no structural level sits on the protective side of the entry
  round   raw ATR stop (atr x ATR) vs the same stop snapped to the nearest round level
          ("snap"), vs pushed just beyond the nearest round level by 0.1 ATR ("beyond"),
          where round level = multiple of 10^(floor(log10 px)-1)

Candle sweep: --interval 1d / 1h / 15m / 5m (4h owed: needs a 1h resample). Bar-count constants
(10-bar swing, 30-bar hold) mean hours / quarter-hours on intraday bars.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import elder_lab_driver as drv  # noqa: E402
from douglas_trade_mgmt_research import BASES  # noqa: E402

FAMILIES = ("offset", "round")
SWING_LB = 10
OFFSETS = (0.25, 0.5, 0.75, 1.0)


def round_step(px):
    return 10.0 ** (np.floor(np.log10(px)) - 1)


def nearest_round(px):
    st = round_step(px)
    return round(px / st) * st


def make_stop(arrs, s, px, d, am, mode, k):
    """-> stop price or None (entry rejected)."""
    h, l, a = arrs
    raw = px - d * am * a[s]
    if mode == "atr":
        return raw
    if mode == "struct":
        lo = l[max(0, s - SWING_LB + 1):s + 1].min() if d == 1 else h[max(0, s - SWING_LB + 1):s + 1].max()
        st = lo - d * k * a[s]
        if d * (px - st) <= 0:
            return None
        return st if d * (px - st) <= am * a[s] else raw
    r = nearest_round(raw)
    if mode == "snap":
        st = r
    elif mode == "beyond":
        st = r - d * 0.1 * a[s]
    else:
        raise ValueError(mode)
    return st if d * (px - st) > 0 else None


def sim(df, sig, direction, am, mode, k=0.0, max_hold=er.MAX_HOLD_BARS, cost=er.COST_ROUND_TRIP):
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    entry, exitf = sig[direction], sig["exit_" + direction]
    n = len(df)
    trades, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px = o[e]
        if px <= 0:
            continue
        stop = make_stop((h, l, a), s, px, d, am, mode, k)
        if stop is None:
            continue
        reason, exit_px, j = None, None, e
        for j in range(e, min(n, e + max_hold + 1)):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                gap = o[j] if j > e else None
                exit_px = stop if gap is None else (min(gap, stop) if d == 1 else max(gap, stop))
                reason = "stop_loss"
                break
            if exitf[j] and j > e:
                exit_px, reason = c[j], "rule_exit"
                break
            if j == e + max_hold:
                exit_px, reason = c[j], "max_hold_timeout"
                break
        if exit_px is None:
            exit_px, reason, j = c[n - 1], "data_end", n - 1
        trades.append({"ret": float(d * (exit_px - px) / px - cost), "hold": int(j - e + 1), "reason": reason})
        free = j
    return trades


def variant_specs(family):
    """-> list of (variant, mode, k)"""
    if family == "offset":
        return [(f"struct_off{str(k).replace('.', 'd')}", "struct", k) for k in OFFSETS]
    if family == "round":
        return [("atr_raw", "atr", 0.0), ("round_snap", "snap", 0.0), ("round_beyond", "beyond", 0.0)]
    raise ValueError(family)


def run_symbol(df, family, tf, aggs):
    for bname, bf in BASES.items():
        try:
            sig = bf(df)
        except Exception as ex:
            print("BASE ERROR", bname, ex, file=sys.stderr)
            continue
        for variant, mode, k in variant_specs(family):
            for direction in ("long", "short"):
                if not sig[direction].any():
                    continue
                for am in er.ATR_MULTS:
                    tag = er.make_tag("stopoffset", f"{bname}_{variant}", direction, tf, {"atr": am})
                    tr = sim(df, sig, direction, am, mode, k)
                    if tr:
                        er.add_trades(aggs.setdefault(tag, er.new_agg()), tr)


def main(argv=None):
    return drv.run(argv, FAMILIES, run_symbol)


if __name__ == "__main__":
    sys.exit(main())
