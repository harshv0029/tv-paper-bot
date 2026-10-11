"""Chan sizing/test add-ons computed from the registry's stored raw metrics (backlog B-453, B-454, B-455).

READ-ONLY on strategy_registry (never edits it). Nothing here changes live sizing: B-453 says "compute the per-tag
Kelly table before any change (no sizing change blind)". Viability is derived at read time from the stored
numbers (CLAUDE.md 2026-10-11 keep-all-data rule); this file only adds derived columns.

Two-point payoff model per tag, loss unit L = 1: win rate w, PF = w*b/((1-w)) => b = PF*(1-w)/w (avg win / avg loss).
  mean m = w*b - (1-w);  var s2 = w*b^2 + (1-w) - m^2
  B-453 Kelly (Chan): f = m / s2 in multiples of the average-loss unit; half-Kelly = f/2 (cap by risk elsewhere).
  B-455 significance: t = m / sqrt(s2) * sqrt(n) (Gaussian statistic; 1.645 = p .05 one-sided), plus Chan's expected-decay
        haircut (live edge assumed half the backtest edge: t/2) and a thin-n flag (n < 100).
  B-454 CPPI per-tag wind-down: cppi_wind() runs the book's rule on a trade-return sequence (floor = equity - D where D is
        the max drawdown allowed, subaccount reset only at new equity highs, retire when wiped); cppi_mc() bootstraps
        the two-point payoff to report the share of paths in which the tag is retired and the median final equity.
        Position size per trade = `risk_frac` of the subaccount per 1.0 loss unit (assumption stated in the output).
Because the two-point model hides the return distribution's tails, the figures are screening numbers, not sizing orders;
a real-return based Kelly needs per-trade returns (owed: replays emit cell sums only).
Usage: python3 scripts/kelly_significance_table.py [out.json]
"""
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def payoff_stats(pfnet, win_pct, n):
    """Return dict(w, b, mean, var, kelly, half_kelly, t_stat, t_haircut) or None if inputs unusable."""
    if pfnet is None or win_pct is None or not n:
        return None
    w = win_pct / 100.0
    if not (0 < w < 1) or pfnet <= 0:
        return None
    b = pfnet * (1 - w) / w
    m = w * b - (1 - w)
    s2 = w * b * b + (1 - w) - m * m
    if s2 <= 0:
        return None
    t = m / math.sqrt(s2) * math.sqrt(n)
    kelly = m / s2
    return dict(w=round(w, 4), b=round(b, 4), mean=round(m, 5), var=round(s2, 5), kelly=round(kelly, 4),
                half_kelly=round(kelly / 2, 4), t_stat=round(t, 3), t_haircut=round(t / 2, 3))


def cppi_wind(returns, drawdown=0.20, risk_frac=0.05, start=1.0):
    """Chan CPPI wind-down. `returns` are per-trade results in loss units (-1 = a full loss).
    Subaccount = equity allowed to be risked; floor resets only at a new equity high; retired when the subaccount hits 0.
    Returns (final_equity, retired_flag, trades_taken)."""
    equity = start
    high = start
    sub = drawdown * start
    taken = 0
    for r in returns:
        if sub <= 1e-9:
            return equity, True, taken
        stake = risk_frac * sub / max(drawdown, 1e-9)  # risk this fraction of the subaccount per loss unit
        pnl = stake * r
        equity += pnl
        sub = max(0.0, sub + pnl)
        taken += 1
        if equity > high:
            high = equity
            sub = drawdown * equity  # reset only at new highs
    return equity, sub <= 1e-9, taken


def cppi_mc(w, b, n_trades=250, paths=2000, seed=11, **kw):
    rng = np.random.default_rng(seed)
    retired, finals = 0, []
    for _ in range(paths):
        r = np.where(rng.random(n_trades) < w, b, -1.0)
        eq, ret, _ = cppi_wind(r, **kw)
        retired += int(ret)
        finals.append(eq)
    return dict(retired_pct=round(100.0 * retired / paths, 1), median_final_equity=round(float(np.median(finals)), 4))


def build(floor=None):
    import strategy_registry as sr
    floor = sr.PFNET_LIVE_FLOOR if floor is None else floor
    rows = []
    for s in sr.REGISTRY:
        m = s.metrics
        if not m or m.pfnet is None:
            continue
        st = payoff_stats(m.pfnet, m.win_rate_pct, m.n_trades)
        if not st:
            continue
        row = dict(name=s.name, pfnet=m.pfnet, win_pct=m.win_rate_pct, n=m.n_trades, universe=m.universe,
                   viable_at_floor=bool(m.pfnet >= floor), thin_n=bool(m.n_trades < 100), **st)
        row["sig_p05"] = bool(st["t_stat"] >= 1.645)
        row["sig_p05_after_haircut"] = bool(st["t_haircut"] >= 1.645)
        if row["viable_at_floor"] and row["kelly"] > 0:
            row["cppi"] = cppi_mc(st["w"], st["b"], paths=200, risk_frac=min(0.05, max(0.005, st["half_kelly"] / 10)))
        rows.append(row)
    return rows


def main():
    rows = build()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "kelly_significance_table.json")
    json.dump({"model": "two-point payoff from registry pfnet/win%/n (screening only)", "rows": rows}, open(out, "w"), indent=0)
    via = [r for r in rows if r["viable_at_floor"]]
    print(f"tags with metrics={len(rows)} viable={len(via)} thin_n_viable={sum(r['thin_n'] for r in via)} "
          f"not_significant_after_haircut={sum(not r['sig_p05_after_haircut'] for r in via)}")
    for r in sorted(via, key=lambda r: -r["half_kelly"])[:25]:
        print(r["name"], "halfK", r["half_kelly"], "t", r["t_stat"], "t/2", r["t_haircut"], "n", r["n"], r.get("cppi"))
    print("wrote", out)


if __name__ == "__main__":
    main()
