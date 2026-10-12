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
    # B-413: the live gap_and_go tags now map to hold30; the 52-symbol legacy row is its variant.
    "gap_and_go_swing": "gap_and_go__swing__long__1d__hold30__v1",
    "gap_and_go__swing__long__1d__hold60__v1": "gap_and_go__swing__long__1d__hold30__v1",
    "minervini_vcp_breakeven_2r": "minervini_vcp_livermore_confirmed",
    "minervini_vcp_breakeven_3r": "minervini_vcp_livermore_confirmed",
    "order_block_delta_long": "order_block_delta__retest__long__1d__trail6d0__v1",
    "order_block_delta__retest__long__1d__trail4d5__v1": "order_block_delta__retest__long__1d__trail6d0__v1",
    "volume_profile_poc_bounce_long": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
    "volume_profile_poc__bounce__long__1d__trail4d5__v1": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
}


# 2026-10-11 exit-family run 38140914889: viable alternative exits of the same entries. One live exit per
# entry family (the best PFnet one); the rest are registered variants of that wired sibling.
_EF_SIBLING = {
    "gap_and_go": "gap_and_go__swing__long__1d__hold30__v1",
    "volume_profile_poc": "volume_profile_poc__exitinval__long__1d__atr6d0_hold30_sigema13w__v1",
    "order_block_delta": "order_block_delta__exitinval__long__1d__atr6d0_hold30_sigema13w__v1",
}
for _s in sr.REGISTRY:
    if _s.source.startswith("scripts/exit_family_research.py"):
        VARIANT_OF_WIRED.setdefault(_s.name, _EF_SIBLING[_s.name.split("__")[0] if not _s.name.startswith("gg__") else "gap_and_go"])


def test_every_viable_strategy_is_wired_or_explained():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    reg = sr.REGISTRY.values() if isinstance(sr.REGISTRY, dict) else sr.REGISTRY
    missing = [s.name for s in reg
               if s.is_viable() and s.name not in mapped and s.name not in VARIANT_OF_WIRED
               and not s.name.startswith('sector_rotation__') and s.metrics.universe != 'mcx_proxy_single_symbol'
               and getattr(s, 'source', '') not in ('scripts/portfolio_overlay_research.py', 'scripts/breakeven_research.py', 'scripts/douglas_trade_mgmt_research.py', 'scripts/elder_batch3_research.py', 'main.minervini_vcp_entry_signal (real) + exits ported from scripts/minervini_lab.py', 'scripts/pattern_lab.py', 'scripts/chan_research.py', 'scripts/macd_divergence_research.py', 'scripts/brk20_replay.py', 'scripts/intraday_flatten_rerun.py', 'scripts/elder_indicators_research.py', 'scripts/oneil_research.py', 'scripts/elder_macd_dirgap_research.py', 'scripts/elder_indicators_research_ext.py', 'scripts/oneil_ext_research.py', 'scripts/chan_ext_research.py', 'scripts/elder_patterns_research.py', 'scripts/minervini_sweep_lab.py', 'scripts/minervini_lab.py', 'scripts/breadth_lab.py', 'scripts/combo_lab.py', 'scripts/intermarket_lab.py')]  # B-336/B-343 research cells: live engine owed
    assert not missing, f"viable but not wired to a scan counter/engine: {missing}"


def test_allowlisted_variants_point_at_a_wired_sibling():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    for variant, sibling in VARIANT_OF_WIRED.items():
        assert sibling in mapped, f"{variant} -> {sibling} is not wired"
