#!/usr/bin/env python3
"""Elder pyramiding research (backlog B-742, with the never-average-down / risk-cap part of
B-743). Research only; no main.py edits.

Elder: add to a winning trend position only when the existing position is at breakeven or
better AND total open risk stays within 2% of equity. Add triggers: Bear Power dips below 0 and
ticks up (long) / Bull Power rallies above 0 and ticks down (short); or Force Index (2) flips
in the trade direction. Uses the unit-ledger accept rule of scripts/portfolio_ledger_research.py
(`_risk`): average-down adds are rejected outright, an add is accepted only when the stop is at
or beyond average cost, and the add's risk plus open risk must stay <= 2% of equity.

Model (equity = 1): the first unit is sized to risk 1% of equity (q0 = 0.01 / (atr x ATR)).
Management is IDENTICAL in every arm, so only the adds differ: stop = atr x ATR from entry, moved
to average cost once the trade shows +1R, then trailed atr x ATR from the extreme (never loosened);
EMA13 rule exit; 30-bar max hold. Adds (max 2) fill at the next open. A stop is on every trade and
protects every unit. Return per trade = total P&L / (q0 x entry) minus 0.8% on each unit's
notional, so noadd and add arms are comparable. Reported extras per tag: adds accepted and the
rejection counts by reason (avg-down / not-breakeven / risk-cap).

Variants: noadd | bear (Bear/Bull Power tick) x add size 0.5 / 1.0 of q0 | fi2 (Force Index 2
flip) x add size 0.5 / 1.0. Both directions (true-price short, triggers from the reciprocal
mirror), ATR 1.5/2/3, two base entries (EMA13 dip, 20-bar breakout), full universe.
Candle sweep: --interval 1d / 1h / 15m / 5m (4h owed). OWED (not in this harness): Vince
margin-call exit and worst-position-first liquidation across concurrent positions (B-743), which
need mark-to-market by date.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import elder_lab_driver as drv  # noqa: E402
from douglas_trade_mgmt_research import BASES  # noqa: E402
from elder_patterns_research import flip  # noqa: E402
from portfolio_ledger_research import _risk  # noqa: E402

FAMILIES = ("pyramid",)
EXTRA = ("adds", "rej_avgdown", "rej_notbe", "rej_riskcap", "trades_with_add")
EQUITY = 1.0
INIT_RISK = 0.01
MAX_RISK = 0.02
MAX_ADDS = 2
VARIANTS = (("noadd", None, 0.0), ("bear_q0d5", "bear", 0.5), ("bear_q1", "bear", 1.0),
            ("fi2_q0d5", "fi2", 0.5), ("fi2_q1", "fi2", 1.0))


def triggers_long(df):
    """Add-trigger bool arrays in the LONG orientation."""
    e = er.ema(df["Close"], 13)
    bear = df["Low"] - e
    up = e > e.shift(1)
    t_bear = up & (bear < 0) & (bear > bear.shift(1))
    fi = er.force_index2(df)
    t_fi = (fi > 0) & (fi.shift(1) <= 0)
    return {"bear": np.asarray(t_bear.fillna(False), bool), "fi2": np.asarray(t_fi.fillna(False), bool)}


def triggers(df):
    return {"long": triggers_long(df), "short": triggers_long(flip(df))}


def accept_add(units, d, stop, padd, qadd):
    """-> (ok, reason). Elder rule via the unit ledger: never average down, stop at/beyond cost,
    total risk after the add <= MAX_RISK of equity."""
    avg = sum(u["px"] * u["qty"] for u in units) / sum(u["qty"] for u in units)
    if (padd - avg) * d < 0:
        return False, "avgdown"
    if (stop - avg) * d < 0:
        return False, "notbe"
    if _risk(units + [{"px": padd, "qty": qadd}], d, stop) > MAX_RISK * EQUITY + 1e-12:
        return False, "riskcap"
    return True, ""


def sim(df, sig, trig, direction, am, trig_kind, addq, max_hold=er.MAX_HOLD_BARS, cost=er.COST_ROUND_TRIP):
    d = 1 if direction == "long" else -1
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    a = er.atr(df).to_numpy()
    entry, exitf = sig[direction], sig["exit_" + direction]
    tarr = trig[direction][trig_kind] if trig_kind else None
    n = len(df)
    out, free = [], 0
    for s in np.flatnonzero(entry):
        if s < free or s + 1 >= n or np.isnan(a[s]) or a[s] <= 0:
            continue
        e = s + 1
        px0 = o[e]
        if px0 <= 0:
            continue
        r1 = am * a[s]
        q0 = INIT_RISK * EQUITY / r1
        units = [{"px": px0, "qty": q0}]
        stop = px0 - d * r1
        extreme, be = px0, False
        cnt = {"adds": 0, "rej_avgdown": 0, "rej_notbe": 0, "rej_riskcap": 0}
        pending, reason, j, closed_px = None, None, e, None
        for j in range(e, min(n, e + max_hold + 1)):
            if pending is not None and j == pending:   # add fills at this bar's open
                ok, why = accept_add(units, d, stop, o[j], addq * q0)
                if ok:
                    units.append({"px": o[j], "qty": addq * q0})
                    cnt["adds"] += 1
                else:
                    cnt["rej_" + {"avgdown": "avgdown", "notbe": "notbe", "riskcap": "riskcap"}[why]] += 1
                pending = None
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                gap = o[j] if j > e else None
                closed_px = stop if gap is None else (min(gap, stop) if d == 1 else max(gap, stop))
                reason = "stop_loss" if not be else "protected_stop"
                break
            extreme = max(extreme, h[j]) if d == 1 else min(extreme, l[j])
            if not be and d * (extreme - px0) >= r1:
                be = True
                avg = sum(u["px"] * u["qty"] for u in units) / sum(u["qty"] for u in units)
                stop = max(stop, avg) if d == 1 else min(stop, avg)
            if be:
                ns = extreme - d * r1
                stop = max(stop, ns) if d == 1 else min(stop, ns)
            if exitf[j] and j > e:
                closed_px, reason = c[j], "rule_exit"
                break
            if j == e + max_hold:
                closed_px, reason = c[j], "max_hold_timeout"
                break
            if (tarr is not None and tarr[j] and cnt["adds"] < MAX_ADDS and j + 1 < n):
                pending = j + 1
        if closed_px is None:
            closed_px, reason, j = c[n - 1], "data_end", n - 1
        pnl = sum(u["qty"] * d * (closed_px - u["px"]) for u in units)
        notional0 = q0 * px0
        costs = sum(cost * u["qty"] * u["px"] for u in units)
        out.append({"ret": float((pnl - costs) / notional0), "hold": int(j - e + 1), "reason": reason, **cnt,
                    "with_add": 1 if cnt["adds"] else 0})
        free = j
    return out


def add_trades(agg, trades):
    er.add_trades(agg, trades)
    for t in trades:
        agg["adds"] += t["adds"]
        agg["rej_avgdown"] += t["rej_avgdown"]
        agg["rej_notbe"] += t["rej_notbe"]
        agg["rej_riskcap"] += t["rej_riskcap"]
        agg["trades_with_add"] += t["with_add"]


def run_symbol(df, family, tf, aggs):
    trig = triggers(df)
    for bname, bf in BASES.items():
        try:
            sig = bf(df)
        except Exception as ex:
            print("BASE ERROR", bname, ex, file=sys.stderr)
            continue
        for variant, kind, q in VARIANTS:
            for direction in ("long", "short"):
                if not sig[direction].any():
                    continue
                for am in er.ATR_MULTS:
                    tag = er.make_tag("pyramid", f"{bname}_{variant}", direction, tf, {"atr": am})
                    tr = sim(df, sig, trig, direction, am, kind, q)
                    if tr:
                        add_trades(aggs.setdefault(tag, drv.new_agg(EXTRA)), tr)


def main(argv=None):
    return drv.run(argv, FAMILIES, run_symbol, EXTRA)


if __name__ == "__main__":
    sys.exit(main())
