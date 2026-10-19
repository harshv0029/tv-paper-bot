import strategy_registry as sr
import main


def test_wired_needs_pfnet_and_30d_hold():
    m = lambda pf, h: sr.Metrics(pfnet=pf, pfgross=pf, win_rate_pct=40, n_trades=100, avg_held_hrs=h)
    d = sr.REGISTRY[0]
    for pf, h, exp in [(1.05, 100.0, True), (0.9, 10.0, False), (1.5, 190.0, False), (1.5, None, False)]:
        d2 = type(d)(**{**d.__dict__, "metrics": m(pf, h)})
        assert d2.is_wired() is exp
