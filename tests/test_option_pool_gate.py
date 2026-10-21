import main
import strategy_registry as sr


def test_pool_only_buy_or_options():
    seen = {"in": 0, "out": 0}
    for tag, name in main._STRATEGY_TAG_TO_REGISTRY_NAME.items():
        strat = next((x for x in sr.REGISTRY if x.name == name), None)
        if strat is None:
            assert main._option_pool_allows(tag) is False
            continue
        cats = {getattr(c, "value", c) for c in strat.categories}
        want = bool(cats & {"buy", "options"})
        assert main._option_pool_allows(tag) is want
        seen["in" if want else "out"] += 1
    assert seen["in"] >= 1 and seen["out"] >= 1


def test_unknown_or_empty_fails_closed():
    assert main._option_pool_allows(None) is False
    assert main._option_pool_allows("no_such_tag") is False
