import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import kelly_significance_table as k  # noqa: E402


def test_payoff_stats_breakeven_and_edge():
    be = k.payoff_stats(1.0, 50.0, 400)
    assert abs(be["mean"]) < 1e-9 and abs(be["kelly"]) < 1e-9 and abs(be["t_stat"]) < 1e-6
    ed = k.payoff_stats(1.5, 45.0, 400)
    assert ed["mean"] > 0 and ed["kelly"] > 0 and ed["half_kelly"] == round(ed["kelly"] / 2, 4)
    assert ed["t_haircut"] == round(ed["t_stat"] / 2, 3)
    assert k.payoff_stats(None, 50, 10) is None and k.payoff_stats(1.2, 100.0, 10) is None


def test_t_stat_grows_with_sqrt_n():
    a, b = k.payoff_stats(1.4, 50.0, 100), k.payoff_stats(1.4, 50.0, 400)
    assert math.isclose(b["t_stat"] / a["t_stat"], 2.0, rel_tol=0.01)


def test_cppi_retires_on_losses_and_resets_only_at_new_highs():
    eq, retired, taken = k.cppi_wind([-1.0] * 200, drawdown=0.2, risk_frac=0.05)
    assert retired and taken < 200 and eq < 1.0
    eq2, retired2, _ = k.cppi_wind([1.0] * 20, drawdown=0.2, risk_frac=0.05)
    assert not retired2 and eq2 > 1.0


def test_cppi_mc_edge_vs_no_edge():
    good = k.cppi_mc(0.55, 1.5, paths=300)
    bad = k.cppi_mc(0.30, 0.8, paths=300)
    assert bad["retired_pct"] > good["retired_pct"]
