"""B-45: gap-and-go's 1.65 PFnet was measured on 1d multi-day swing holds, so no
gap_and_go registry entry may sit in the BUY (intraday) category or inherit it there."""
import strategy_registry as sr

# the true same-day intraday family (own tags, B-45 run 38277225522) legitimately sits in BUY; only SWING tags are guarded
_INTRADAY = "gap_and_go_intraday__"


def test_gap_and_go_swing_entries_never_in_buy_category():
    found = [s for s in sr.REGISTRY if s.name.startswith("gap_and_go") and "short" not in s.name
             and not s.name.startswith(_INTRADAY)]
    assert found, "gap_and_go swing entries missing from registry"
    for s in found:
        assert sr.TradeCategory.BUY not in s.categories, s.name
        assert sr.TradeCategory.SWING in s.categories, s.name


def test_gap_and_go_not_on_buy_leaderboard():
    names = {s.name for s in sr.REGISTRY if sr.TradeCategory.BUY in s.categories}
    assert not any(n.startswith("gap_and_go") and not n.startswith(_INTRADAY) for n in names)
