"""B-338 (2026-10-10): every viable strategy (PFnet >= floor) must either be
mapped in main._STRATEGY_TAG_TO_REGISTRY_NAME (so it gets a scan counter and
runs in its category's engine) or be listed below with the reason it has no
separate live path. A NEW viable strategy that is neither fails the build, so
it can never sit viable-but-unwired and silently untraded."""
import main
import strategy_registry as sr

# Registered research variants of a family whose live tag is already mapped.
# They are viable on paper but the live engine runs the mapped sibling.
VARIANT_OF_WIRED = {
    "gap_and_go__swing__long__1d__hold30__v1": "gap_and_go_swing",
    "gap_and_go__swing__long__1d__hold60__v1": "gap_and_go_swing",
    "minervini_vcp_breakeven_2r": "minervini_vcp_livermore_confirmed",
    "minervini_vcp_breakeven_3r": "minervini_vcp_livermore_confirmed",
    "order_block_delta_long": "order_block_delta__retest__long__1d__trail6d0__v1",
    "order_block_delta__retest__long__1d__trail4d5__v1": "order_block_delta__retest__long__1d__trail6d0__v1",
    "volume_profile_poc_bounce_long": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
    "volume_profile_poc__bounce__long__1d__trail4d5__v1": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
}


def test_every_viable_strategy_is_wired_or_explained():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    reg = sr.REGISTRY.values() if isinstance(sr.REGISTRY, dict) else sr.REGISTRY
    missing = [s.name for s in reg
               if s.is_viable() and s.name not in mapped and s.name not in VARIANT_OF_WIRED]
    assert not missing, f"viable but not wired to a scan counter/engine: {missing}"


def test_allowlisted_variants_point_at_a_wired_sibling():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    for variant, sibling in VARIANT_OF_WIRED.items():
        assert sibling in mapped, f"{variant} -> {sibling} is not wired"
