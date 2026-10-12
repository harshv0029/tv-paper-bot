"""Read-time edge statistics derived from stored registry Metrics (B-539/B-540).

Nothing here is stored or flagged: every number is recomputed from the raw
Metrics (pfnet, win_rate_pct, n_trades, avg_net_inr) so a changed viability
definition re-decides every strategy without re-running any backtest.

Approximation (stated plainly): the registry keeps pooled aggregates, not
per-trade returns, so the bootstrap CI resamples a two-point trade model
(win = R units, loss = 1 unit, where R is implied by PFnet and win rate).
It captures sample-size uncertainty, not fat-tail shape. Replace with a
per-trade bootstrap once a run emits trade lists.
"""
from __future__ import annotations

import random
from typing import Optional

MIN_N_RESEARCH = 100   # B-540: minimum trades for a research verdict
MIN_N_LIVE_BLOCK = 20  # B-540: minimum trades for a live 20-trade block


def implied_payoff_ratio(pfnet: float, win_rate_pct: float) -> Optional[float]:
    """R = avgWin/avgLoss implied by PF = p*R / ((1-p)*1)."""
    p = win_rate_pct / 100.0
    if not (0.0 < p < 1.0) or pfnet <= 0:
        return None
    return pfnet * (1.0 - p) / p


def expectancy_per_loss_unit(pfnet: float, win_rate_pct: float) -> Optional[float]:
    """E = p*R - (1-p), in units of the average loss. >0 iff PFnet>1."""
    r = implied_payoff_ratio(pfnet, win_rate_pct)
    if r is None:
        return None
    p = win_rate_pct / 100.0
    return p * r - (1.0 - p)


def passes_edge_gate(metrics, min_n: int = MIN_N_RESEARCH) -> Optional[bool]:
    """B-539: net expectancy > 0 with at least min_n trades. None = cannot judge."""
    if metrics is None or metrics.n_trades < min_n:
        return None
    e = expectancy_per_loss_unit(metrics.pfnet, metrics.win_rate_pct)
    return None if e is None else e > 0


def bootstrap_pfnet_ci(pfnet: float, win_rate_pct: float, n_trades: int,
                       n_boot: int = 2000, alpha: float = 0.05, seed: int = 7):
    """(lo, hi) percentile CI on PFnet under the two-point model, or None."""
    r = implied_payoff_ratio(pfnet, win_rate_pct)
    if r is None or n_trades < 2:
        return None
    p = win_rate_pct / 100.0
    rng = random.Random(seed)
    pfs = []
    for _ in range(n_boot):
        wins = sum(1 for _ in range(n_trades) if rng.random() < p)
        losses = n_trades - wins
        pfs.append(float("inf") if losses == 0 else wins * r / losses)
    pfs.sort()
    lo = pfs[int((alpha / 2) * (n_boot - 1))]
    hi = pfs[int((1 - alpha / 2) * (n_boot - 1))]
    return lo, hi


def promotion_verdict(metrics, floor: float, min_n: int = MIN_N_RESEARCH) -> str:
    """B-540: 'promote' / 'demote' / 'hold' (CI spans floor) / 'insufficient_n' / 'no_metrics'."""
    if metrics is None:
        return "no_metrics"
    if metrics.n_trades < min_n:
        return "insufficient_n"
    ci = bootstrap_pfnet_ci(metrics.pfnet, metrics.win_rate_pct, metrics.n_trades)
    if ci is None:
        return "no_metrics"
    lo, hi = ci
    if lo >= floor:
        return "promote"
    if hi < floor:
        return "demote"
    return "hold"
