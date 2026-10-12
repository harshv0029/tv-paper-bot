import strategy_edge_stats as s
from strategy_registry import Metrics


def M(pf, w, n):
    return Metrics(pfnet=pf, pfgross=pf, win_rate_pct=w, n_trades=n)


def test_expectancy_sign_matches_pf():
    assert s.expectancy_per_loss_unit(1.5, 40) > 0
    assert s.expectancy_per_loss_unit(0.8, 40) < 0
    assert abs(s.expectancy_per_loss_unit(1.0, 40)) < 1e-9
    assert s.expectancy_per_loss_unit(1.2, 0) is None


def test_edge_gate_needs_n():
    assert s.passes_edge_gate(M(1.5, 40, 50)) is None
    assert s.passes_edge_gate(M(1.5, 40, 500)) is True
    assert s.passes_edge_gate(M(0.7, 40, 500)) is False
    assert s.passes_edge_gate(None) is None


def test_ci_and_verdict():
    lo, hi = s.bootstrap_pfnet_ci(1.3, 40, 300)
    assert lo < 1.3 < hi
    assert s.bootstrap_pfnet_ci(1.3, 40, 300) == (lo, hi)  # deterministic
    assert s.promotion_verdict(M(1.15, 40, 150), 1.1) == "hold"
    assert s.promotion_verdict(M(3.0, 40, 2000), 1.1) == "promote"
    assert s.promotion_verdict(M(0.5, 40, 2000), 1.1) == "demote"
    assert s.promotion_verdict(M(3.0, 40, 10), 1.1) == "insufficient_n"
