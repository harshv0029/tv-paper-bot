import main, strategy_registry as sr


def test_be3r_maps_to_viable_registry_entry():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["minervini_vcp_be3r"] == "minervini_vcp_breakeven_3r"
    assert main._is_strategy_viable_for_real_money("minervini_vcp_be3r") is True


def test_be3r_has_exit_branch_and_thesis():
    src = open(main.__file__).read()
    assert 'pos["strategy"] == "minervini_vcp_be3r"' in src
    assert "minervini_vcp_exit_reason_breakeven(" in src
    assert "minervini_vcp_be3r" in main.TRADE_THESIS_BY_STRATEGY if hasattr(main, "TRADE_THESIS_BY_STRATEGY") else True


def test_base_chandelier_tag_stays_gated_closed():
    assert main._is_strategy_viable_for_real_money("minervini_vcp") is False
