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


def simulate_marked_ledger(trades, dates, equity=1.0, max_open=10, margin_frac=0.2, risk_frac_of_eq=0.01,
                           worst_first_on_full=True, margin_exit=True):
    """B-743: dated, mark-to-market portfolio ledger for the Vince rules. Research only, pure.

    trades: dicts(id, side(+1/-1), entry_date, exit_date, entry, stop, marks{date: price}); a trade with no stop
    is refused (no-trade-without-SL). Missing marks carry the last mark forward. qty is sized so the stop distance
    risks `risk_frac_of_eq` of current equity. Each date: (1) close trades whose exit_date == date, (2) mark open
    positions, (3) margin check (used margin = margin_frac * notional); if it exceeds equity+floating,
    margin_call_exit() closes worst mark-to-market first (never topped up), (4) admit entries; when full and
    worst_first_on_full, the worst open position is liquidated to make room only if it is currently losing (a
    winner is never closed to admit a new trade). No adds exist, so never-average-down is structural.
    Returns dict(final_equity, n_closed, n_refused, closes=[(id, date, pnl, reason)], max_dd_pct)."""
    by_entry, closes, refused = {}, [], 0
    for t in trades:
        if not t.get("stop"):
            refused += 1
            continue
        by_entry.setdefault(t["entry_date"], []).append(t)
    open_p, st = {}, {"eq": float(equity), "peak": float(equity), "dd": 0.0}

    def close(pid, d, reason):
        p = open_p.pop(pid)
        pnl = (p["last"] - p["t"]["entry"]) * p["t"]["side"] * p["qty"]
        st["eq"] += pnl
        st["peak"] = max(st["peak"], st["eq"])
        st["dd"] = max(st["dd"], 1 - st["eq"] / st["peak"])
        closes.append((pid, d, round(pnl, 6), reason))

    def as_pos(margin_of):
        return [{"id": k, "side": p["t"]["side"], "qty": p["qty"], "entry": p["t"]["entry"], "mark": p["last"],
                 "margin": margin_of(p)} for k, p in open_p.items()]

    for d in dates:
        for p in open_p.values():
            p["last"] = p["t"]["marks"].get(d, p["last"])
        for pid in [k for k, p in open_p.items() if p["t"]["exit_date"] == d]:
            close(pid, d, "exit")
        if margin_exit and open_p:
            pos = as_pos(lambda p: margin_frac * p["last"] * p["qty"])
            floating = sum((x["mark"] - x["entry"]) * x["side"] * x["qty"] for x in pos)
            for pid in margin_call_exit(pos, st["eq"] + floating, st["eq"] + floating,
                                        sum(x["margin"] for x in pos)):
                close(pid, d, "margin_call_exit")
        for t in by_entry.get(d, []):
            dist = abs(t["entry"] - t["stop"])
            if dist <= 0:
                refused += 1
                continue
            if len(open_p) >= max_open:
                if not (worst_first_on_full and open_p):
                    continue
                worst = liquidate_worst_first(as_pos(lambda p: 1.0), 1.0)[0]
                wp = open_p[worst]
                if (wp["last"] - wp["t"]["entry"]) * wp["t"]["side"] >= 0:
                    continue
                close(worst, d, "worst_first_make_room")
            open_p[t["id"]] = {"t": t, "qty": risk_frac_of_eq * st["eq"] / dist, "last": t["entry"]}
    for pid in list(open_p):
        close(pid, dates[-1] if dates else "", "end_of_data")
    return {"final_equity": round(st["eq"], 6), "n_closed": len(closes), "n_refused": refused, "closes": closes,
            "max_dd_pct": round(100 * st["dd"], 4)}


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
