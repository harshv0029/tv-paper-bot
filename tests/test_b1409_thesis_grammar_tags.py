import main


def test_grammar_tag_uses_family_thesis_and_names_variant():
    tag = "order_block_delta__exitinval__long__1d__atr6d0_hold30_sigema13w__v1"
    txt = main._build_trade_thesis(tag, 36.76, 33.33, None, True)
    assert "could not be identified" not in txt and "Order Block" in txt and tag in txt


def test_orphan_tag_has_its_own_thesis():
    assert main._trade_thesis_components_for(main.ORPHAN_SWING_STRATEGY_TAG) is main._TRADE_THESIS_ORPHAN
    assert "could not be identified" not in main._build_trade_thesis("swing_rerouted_orphan", 188.75, 175.12, None, True)


def test_unknown_tag_keeps_default():
    assert main._trade_thesis_components_for("nope__x__long__1d__p1__v1") is main._TRADE_THESIS_DEFAULT
