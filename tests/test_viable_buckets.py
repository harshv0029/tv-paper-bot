import strategy_registry as sr
from strategy_registry import StrategyDef, Metrics, TradeCategory as C, AssetClass, StrategyStatus, TRADING_HOURS_PER_DAY as H


def _s(name, cats, pf, days):
    return StrategyDef(name=name, asset_class=list(AssetClass)[0], categories=cats, timeframe="1d",
                       status=list(StrategyStatus)[0],
                       metrics=Metrics(pfnet=pf, pfgross=pf, win_rate_pct=40.0, n_trades=100,
                                       avg_held_hrs=None if days is None else days * H))


def _find(res, cat, name):
    return [(b["band"], h["band"]) for b in res[cat]["pfnet_buckets"] for h in b["hold_buckets"]
            for s in h["strategies"] if s["name"] == name]


def test_bucketing_bands_and_multicategory():
    reg = [_s("a", (C.SWING, C.BUY), 1.2, 0.5), _s("b", (C.SWING,), 1.7, 10), _s("c", (C.SWING,), 2.5, 31),
           _s("d", (C.SWING,), 1.0, 5), _s("e", (C.SWING,), 1.35, None), _s("f", (C.SWING,), 1.1, 3)]
    r = sr.bucket_viable_strategies(reg)
    assert _find(r, "swing", "a") == [("1.1-1.3", "<=1d")]
    assert _find(r, "buy", "a") == [("1.1-1.3", "<=1d")]  # repeated per category
    assert _find(r, "swing", "b") == [("1.6-2.0", "7-15d")]
    assert _find(r, "swing", "c") == [("2.0+", ">30d")]
    assert _find(r, "swing", "d") == []  # below floor, not viable
    assert _find(r, "swing", "e") == [("1.3-1.6", sr.HOLD_UNRECORDED)]
    assert _find(r, "swing", "f") == [("1.1-1.3", "1-3d")]  # boundary 3d -> 1-3d
    assert r["swing"]["count"] == 5 and r["short_sell"]["count"] == 0


def test_real_registry_counts_match_viable():
    r = sr.bucket_viable_strategies()
    for cat in sr.TradeCategory:
        want = sum(1 for s in sr.REGISTRY if cat in s.categories and s.is_viable() is True)
        assert r[cat.value]["count"] == want
