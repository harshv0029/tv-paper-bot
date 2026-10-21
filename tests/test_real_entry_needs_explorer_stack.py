"""2026-10-21 user: real-money entry comes only from the active explorer viable stack; PFnet >= 1 alone wires scanning."""
import main
import strategy_registry as sr

TAG = "chan_gap__buy_on_gap__long__1d__atr4d0_top10__v1"


def test_no_stack_means_no_real_entry_but_still_wired(monkeypatch):
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", False)
    sr.VIABLE_OVERRIDES.clear()
    assert main.REAL_ENTRY_REQUIRES_EXPLORER_STACK is True
    assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is False
    assert main._is_strategy_wired(TAG) is True  # PFnet 1.445 >= 1, hold 6.25h: scanned, paper only


def test_stack_membership_opens_real_entry(monkeypatch):
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", True)
    sr.VIABLE_OVERRIDES.clear()
    assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is False  # stack active, tag not in it
    sr.VIABLE_OVERRIDES.add(main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG])
    assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is True
    sr.VIABLE_OVERRIDES.clear()
