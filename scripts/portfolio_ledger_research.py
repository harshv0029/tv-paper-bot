#!/usr/bin/env python3
"""Unit-ledger primitives for B-742 (Elder pyramiding) and B-743 (Vince portfolio rules). Research only.

Pure functions, no network. Existing simulators (simulate_portfolio in portfolio_overlay_research.py)
are single-unit per trade; these add what they lack:
  pyramid_position       multi-unit position with the Elder add rule: add only when the existing
                         position is at breakeven or better (stop at/beyond average cost, in the
                         profitable direction) AND total open risk after the add stays <= max_risk
                         (default 2% of equity). Adds at a worse price than average are rejected
                         outright (never average down).
  liquidate_worst_first  Vince: when lightening up or facing a margin call, close the worst
                         mark-to-market position first and exit rather than meet the call.
Both directions: side=+1 long, -1 short. Every position carries a stop (no-trade-without-SL).
OWED (needs Actions): the collect stage must emit per-trade bar paths / add-trigger bars so these run
on the full universe across 1h/15m/1d with the Elder triggers (Bear/Bull Power tick, FI2 flip);
until then this module is verified on synthetic paths only.
"""
from __future__ import annotations


def _risk(units, side, stop):
    """Open risk: sum over units of (entry - stop) * side * qty, floored at 0 per unit (locked profit is not risk)."""
    return sum(max(0.0, (u["px"] - stop) * side * u["qty"]) for u in units)


def pyramid_position(side, entry, stop, qty, equity, adds, max_risk=0.02):
    """adds: list of (price, qty, new_stop). Returns dict(units, stop, accepted, rejected).
    The initial unit must itself respect max_risk (ValueError otherwise: no oversized first entry)."""
    units = [{"px": entry, "qty": qty}]
    if _risk(units, side, stop) > max_risk * equity + 1e-9:
        raise ValueError("initial risk exceeds cap")
    acc, rej = [], []
    for px, q, new_stop in adds:
        avg = sum(u["px"] * u["qty"] for u in units) / sum(u["qty"] for u in units)
        if (px - avg) * side < 0:
            rej.append((px, q, "average_down"))
            continue
        ns = new_stop if (new_stop - stop) * side >= 0 else stop  # stop only ever moves in profit direction
        if (ns - avg) * side < 0:
            rej.append((px, q, "not_breakeven"))
            continue
        trial = units + [{"px": px, "qty": q}]
        if _risk(trial, side, ns) > max_risk * equity + 1e-9:
            rej.append((px, q, "risk_cap"))
            continue
        units, stop = trial, ns
        acc.append((px, q, ns))
    return {"units": units, "stop": stop, "accepted": acc, "rejected": rej}


def liquidate_worst_first(positions, need_release):
    """positions: dicts(id, side, qty, entry, mark, margin). Returns ids to close, worst
    mark-to-market first, until released margin >= need_release."""
    order = sorted(positions, key=lambda p: (p["mark"] - p["entry"]) * p["side"] * p["qty"])
    out, freed = [], 0.0
    for p in order:
        if freed >= need_release:
            break
        out.append(p["id"])
        freed += p["margin"]
    return out


def margin_call_exit(positions, equity, margin_available, margin_required):
    """Vince: never meet a margin call. If required margin exceeds available, return ids to EXIT (worst
    mark-to-market first) until the shortfall is released; empty list when no call. No top-up is ever assumed;
    `equity` is accepted for logging symmetry only."""
    shortfall = margin_required - margin_available
    if shortfall <= 0:
        return []
    return liquidate_worst_first(positions, shortfall)


def correlation_screen(returns_by_sym, candidates, open_syms, max_corr=0.7, min_overlap=20):
    """B-746 Elder diversification: from `candidates` (preference order) keep those whose |corr| with EVERY already
    held symbol is <= max_corr (accepted candidates join the held set). returns_by_sym: {sym: [float|None]} date
    aligned. Series with too little overlap or zero variance pass (correlation cannot be shown). Pure, no network."""
    import math

    def corr(a, b):
        pr = [(x, y) for x, y in zip(a, b) if x is not None and y is not None
              and not math.isnan(x) and not math.isnan(y)]
        if len(pr) < min_overlap:
            return 0.0
        mx = sum(p[0] for p in pr) / len(pr)
        my = sum(p[1] for p in pr) / len(pr)
        sx = sum((p[0] - mx) ** 2 for p in pr) ** 0.5
        sy = sum((p[1] - my) ** 2 for p in pr) ** 0.5
        return 0.0 if sx == 0 or sy == 0 else sum((p[0] - mx) * (p[1] - my) for p in pr) / (sx * sy)

    held, out = list(open_syms), []
    for c in candidates:
        if all(abs(corr(returns_by_sym.get(c, []), returns_by_sym.get(o, []))) <= max_corr for o in held):
            out.append(c)
            held.append(c)
    return out
