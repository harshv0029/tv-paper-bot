import strategy_registry as sr
import main


def test_wired_needs_only_pfnet():
    m = lambda pf, h: sr.Metrics(pfnet=pf, pfgross=pf, win_rate_pct=40, n_trades=100, avg_held_hrs=h)
    d = sr.REGISTRY[0]
    for pf, h, exp in [(1.05, 100.0, True), (0.9, 10.0, False), (1.5, 190.0, True), (1.5, None, True), (1.0, 5000.0, True)]:
        d2 = type(d)(**{**d.__dict__, "metrics": m(pf, h)})
        assert d2.is_wired() is exp



def test_replay_owed_tag_still_wired_for_scanning_but_not_entry(monkeypatch):
    by_name = {x.name: x for x in sr.REGISTRY}
    tag = next(t for t, n in main._STRATEGY_TAG_TO_REGISTRY_NAME.items()
               if n in by_name and by_name[n].metrics is not None and by_name[n].metrics.pfnet >= sr.PFNET_LIVE_FLOOR)
    monkeypatch.setattr(main, "REPLAY_OWED_TAGS", frozenset(main.REPLAY_OWED_TAGS) | {tag})
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", True)
    assert main._is_strategy_wired(tag) is True
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is False
