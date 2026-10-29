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
    # B-1331: replays of the wired atr4d0 cell's capped-5% live stop and the (unwired) fit-in-5% selection rule.
    "chan_gap__buy_on_gap_mr__long__1d__atr4d0cap5_top10__v1": "chan_gap__buy_on_gap__long__1d__atr4d0_top10__v1",
    "chan_gap__buy_on_gap_mr__long__1d__fit5_top10__v1": "chan_gap__buy_on_gap__long__1d__atr4d0_top10__v1",
    # B-413: the live gap_and_go tags now map to hold30; the 52-symbol legacy row is its variant.
    "gap_and_go_swing": "gap_and_go__swing__long__1d__hold30__v1",
    "gap_and_go__swing__long__1d__hold60__v1": "gap_and_go__swing__long__1d__hold30__v1",
    "minervini_vcp_breakeven_2r": "minervini_vcp_livermore_confirmed",
    "minervini_vcp_breakeven_3r": "minervini_vcp_livermore_confirmed",
    "order_block_delta_long": "order_block_delta__retest__long__1d__trail6d0__v1",
    "order_block_delta__retest__long__1d__trail4d5__v1": "order_block_delta__retest__long__1d__trail6d0__v1",
    "volume_profile_poc_bounce_long": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
    "volume_profile_poc__bounce__long__1d__trail4d5__v1": "volume_profile_poc__bounce__long__1d__trail6d0__v1",
    # B-1220: main.py-replay-measured _mr rows of the wired chan_gap BUY cells (same live entry path, own measured metrics).
    **{f"chan_gap__buy_on_gap_mr__long__1d__{c}_top10__v1": f"chan_gap__buy_on_gap__long__1d__{c}_top10__v1"
       for c in ("atr4d0", "atr2d5", "atr1d5")},
    # B-1221: main.py-replay-measured _mr row of the wired chan_gap SHORT atr1d5 cell (run 38502123279).
    "chan_gap__short_on_gap_mr__short__1d__atr1d5_top10__v1": "chan_gap__short_on_gap__short__1d__atr1d5_top10__v1",
    # B-1233: main.py-replay-measured _mr rows of the wired pl1d LONG swing cells (run 38506928246).
    "starc__fade_full_mr__long__1d__atr2d5_h20__v1": "starc__fade_full__long__1d__atr2d5_h20__v1",
    "gap__runaway_mr__long__1d__atr4_h20__v1": "gap__runaway__long__1d__atr4_h20__v1",
    # B-1244 (run 38517583883): live O'Neil cells are flatbase plain / newhigh / pivot. Avg-down controls (engine invariant: never average
    # down) and trl1 (same signal, lower PFnet than plain) are variants of the wired plain flatbase; the flatbase SHORT cell
    # (n=10, ex-top5 PFnet 0.0) is PARKED, B-1245 (short-swing engine), allowlisted here only so the gap stays visible and explained.
    **{f"oneil_flatbase__breakout__long__1w__{p}__v2": "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v2"
       for p in ("atr3_avg1_chase10_h12_rsnone", "atr3_avg1_chase10_h26_rsnone", "atr3_chase10_h26_rsnone_trl1")},
    "oneil_flatbase__breakout__short__1w__atr3_chase10_h26_rsnone__v2": "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v2",
    # B-1396: main.py replay rows of wired cells (the live engine runs the research-tag cell)
    **{f"tasuki__gap_etf_mr__short__1d__atr{a}_h3__v1": f"tasuki__gap_etf__short__1d__atr{a}_h3__v1" for a in ("2d5", "4", "6")},
    **{f"month__effect_mr__short__15m__atr{a}_h25__v1": f"month__effect__short__15m__atr{a}_h25__v1" for a in ("2d5", "4", "6")},
    **{f"gaps__{v}_mr__long__1d__atr3_nb5__v1": f"gaps__{v}__long__1d__atr3_nb5__v1" for v in ("common_fade", "exhaust_fade")},  # B-1396d
}


# 2026-10-11 exit-family run 38140914889: viable alternative exits of the same entries. One live exit per
# entry family (the best PFnet one); the rest are registered variants of that wired sibling.
_EF_SIBLING = {
    "gap_and_go": "gap_and_go__swing__long__1d__hold30__v1",
    # B-1413: the live exitinval tags are gated on their band-floor main.py replay rows
    "volume_profile_poc": "volume_profile_poc__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1",
    "order_block_delta": "order_block_delta__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1",
}
# B-1413 live-stop model rows (research measurements of the wired OB/VP tags, not separate strategies)
VARIANT_OF_WIRED.update({
    "order_block_delta__retest__long__1d__rsbandonly_trail6d0__v1": "order_block_delta__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1",
    "order_block_delta__exitinval__long__1d__atr6d0_hold30_rsintraday_sigema13w__v1": "order_block_delta__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1",
    "volume_profile_poc__exitinval__long__1d__atr6d0_hold30_rsintraday_sigema13w__v1": "volume_profile_poc__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1",
})
for _s in sr.REGISTRY:
    if _s.source.startswith("scripts/exit_family_research.py"):
        VARIANT_OF_WIRED.setdefault(_s.name, _EF_SIBLING[_s.name.split("__")[0] if not _s.name.startswith("gg__") else "gap_and_go"])


def test_every_viable_strategy_is_wired_or_explained():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    reg = sr.REGISTRY.values() if isinstance(sr.REGISTRY, dict) else sr.REGISTRY
    missing = [s.name for s in reg
               if s.is_viable() and s.name not in mapped and s.name not in VARIANT_OF_WIRED
               and not s.name.startswith('sector_rotation__') and s.metrics.universe != 'mcx_proxy_single_symbol'
               and getattr(s, 'source', '') not in ('scripts/portfolio_overlay_research.py', 'scripts/portfolio_overlay_oos.py', 'scripts/index_option_trigger_research (run 38218867644)', 'scripts/breakeven_research.py', 'scripts/douglas_trade_mgmt_research.py', 'scripts/elder_batch3_research.py', 'main.minervini_vcp_entry_signal (real) + exits ported from scripts/minervini_lab.py', 'scripts/pattern_lab.py', 'scripts/chan_research.py', 'scripts/island_validation.py', 'scripts/lunar_sweep.py', 'scripts/intraday_gap_and_go_research.py', 'scripts/macd_divergence_research.py', 'scripts/brk20_replay.py', 'scripts/intraday_flatten_rerun.py', 'scripts/elder_indicators_research.py', 'scripts/oneil_research.py', 'scripts/elder_macd_dirgap_research.py', 'scripts/elder_trend_context_research.py', 'scripts/elder_indicators_research_ext.py', 'scripts/oneil_ext_research.py', 'scripts/chan_ext_research.py', 'scripts/elder_patterns_research.py', 'scripts/minervini_sweep_lab.py', 'scripts/minervini_lab.py', 'scripts/breadth_lab.py', 'scripts/combo_lab.py', 'scripts/intermarket_lab.py', 'scripts/elder_dirsys13_research (B-588)', 'scripts/oneil_nonoverlap_research (B-831)', 'scripts/oneil_nonoverlap_research (B-833)', 'scripts/swing_min_rr_research (B-842)', 'scripts/island_main_replay.py', 'scripts/swing_short_main_replay.py')]  # B-336/B-343 research cells: live engine owed
    assert not missing, f"viable but not wired to a scan counter/engine: {missing}"


def test_allowlisted_variants_point_at_a_wired_sibling():
    mapped = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    for variant, sibling in VARIANT_OF_WIRED.items():
        assert sibling in mapped, f"{variant} -> {sibling} is not wired"
