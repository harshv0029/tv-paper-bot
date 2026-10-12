import strategy_registry as sr
import strategy_registry_elderge11 as eg


def test_rr_tag_alphabetical_params():
    assert eg.rr_tag("gaps__exhaust_fade__long__1d__atr3_nb5__v1") == "gaps__exhaust_fade__long__1d__atr3_nb5_rr1__v1"
    assert eg.rr_tag("macd__hist_exhaust__long__1d__atr3_zf1__v1") == "macd__hist_exhaust__long__1d__atr3_rr1_zf1__v1"


def test_registered_with_raw_metrics_research_only():
    by = {s.name: s for s in sr.REGISTRY}
    s = by["gaps__exhaust_fade__long__1d__atr3_nb5_rr1__v1"]
    m = s.metrics
    assert (m.pfnet, m.pfgross, m.win_rate_pct, m.n_trades) == (1.252, 2.009, 34.84, 4412)
    assert s.entry_fn is None and s.status == sr.StrategyStatus.RESEARCH
    # the original v1 tag is untouched (never overwritten)
    assert by["gaps__exhaust_fade__long__1d__atr3_nb5__v1"].metrics.pfnet == 1.246
    assert by["gaps__exhaust_fade__short__1d__atr3_nb4_rr1__v1"].categories == (sr.TradeCategory.SHORT_SELL,)
    mine = [n for n in by if "_rr1" in n and n.startswith(("gaps__exhaust_fade", "gaps__common_fade", "macd__hist_exhaust"))]
    assert len(mine) == 42
