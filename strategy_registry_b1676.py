"""B-1676 (user 2026-11-23): PAPER-only most-active index option momentum, run in-process on the View 6 (B-1675) data.
No result yet, so metrics=None (viability can't be judged; never wired). Real-money wiring needs the user's yes plus
pooled PFnet > 1.00. Per-category coverage: options (single-leg index long CE/PE) only."""
import strategy_registry as sr

TAG = "fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1"
STRICT_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti__long_opt__5m__trail2__v1"  # B-1677
OIG_TAG = "fno_mostactive_momo__top3_max_gain_oigreeks__long_opt__5m__trail2__v1"  # B-1681
STRICT_OIG_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti_oigreeks__long_opt__5m__trail2__v1"  # B-1686
V2_TAG = "fno_mostactive_momo__mtfmomo_oibuild_greeks_ivrel__long_opt__5m__trail2__v1"  # B-1714
V3_TAG = "fno_mostactive_momo__fast5m_idxconfirm_delta_ivrel__long_opt__5m__trail2_hold15__v1"  # B-1715 (retired)
V3B_TAG = "fno_mostactive_momo__fast5m_idxconfirm_delta_ivrel_alldte__long_opt__5m__trail2_hold15__v1"  # B-1717: ACTIVE
V3B_T5_TAG = "fno_mostactive_momo__fast5m_idxconfirm_delta_ivrel_alldte__long_opt__5m__trail5_hold15__v1"  # B-1718
V4_T12_TAG = "fno_mostactive_momo__trendday_pullback5m_delta_ivrel_alldte__long_opt__5m__trail12_tgt12_hold15__v1"  # B-1728
V4_T5_TAG = "fno_mostactive_momo__trendday_pullback5m_delta_ivrel_alldte__long_opt__5m__trail5_tgt12_hold15__v1"  # B-1728
V4NB_TAG = "fno_mostactive_momo__trendday_nobreadth_pullback5m_delta_ivrel_alldte__long_opt__5m__trail12_tgt12_hold15__v1"  # B-1744
V4NBW_TAG = ("fno_mostactive_momo__trendday_nobreadth_pullback5m_delta_ivrel_alldte_0930to1430__long_opt__5m__"
             "trail12_tgt12_hold15__v1")  # B-1744
ATMC_TAG = "fno_atmchain_momo__atm10_mom5m15m_idxconfirm_delta_ivrel__long_opt__5m__trail2_hold15__v1"  # B-1757
RETIRED_V3 = ("RETIRED 2026-11-25 before deploy, 0 trades (B-1717, user: include expiry-day contracts, the 2% max SL "
              "then trail caps the loss; replaced by " + V3B_TAG + "). ")
RETIRED_V2 = ("RETIRED 2026-11-25 before deploy, 0 trades (B-1715, user: trades exit within 15 min, do not wait for "
              "1 h; research first): replaced by the fast 5-15 min plan. ")
RETIRED_V1 = ("RETIRED 2026-11-25 (B-1714, user: research OI/Greeks/% change and plan the paper entry): 0 entries in "
              "its run (one largest-day-% candidate per scan, OI build blank on Kotak rows). ")
RETIRED = "RETIRED 2026-11-23 (B-1686, user: one strategy = strict sentiment + OI/Greeks): no new entries. "


def _build_base():
    return [sr.StrategyDef(
        name=TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_step (B-1676), PAPER forward test on NSE most-active index options",
        evidence="Paper forward test only (fno_momo_paper_trades, /fno-momo-paper); no backtest yet.",
        notes=(RETIRED + "Every 5 min 09:30-14:30 IST: top 3 index options by contracts traded per index, largest positive "
               "% change; enter long if CE: index and NIFTY up / PE: both down. Exits: trailing SL 2% of premium from "
               "peak, out of top 3 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=STRICT_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_sentiment_strict (B-1677), PAPER forward test beside B-1676 v1",
        evidence="Paper forward test only (fno_momo_paper_trades tag column, /fno-momo-paper?tag=); no backtest yet.",
        notes=(RETIRED + "B-1676 with a strict ENTRY gate (user 2026-11-23): index and NIFTY day change >= 0.25% in the trade "
               "direction, index beyond its day open, NIFTY 50 breadth >= 1.5x, INDIA VIX up < 5% for a CE. Missing "
               "datum = no entry. Exits as v1 (2% trail). PAPER ONLY."),
    ), sr.StrategyDef(
        name=OIG_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_oi_greeks_gate (B-1681), PAPER forward test beside B-1676/B-1677",
        evidence="Paper forward test only; no backtest possible yet (no free intraday option history).",
        notes=(RETIRED + "B-1676 basic sentiment plus an OI + Greeks ENTRY gate (user 2026-11-23 'use OI and Greeks'): the "
               "contract's OI rising with its premium (long buildup, not short covering), Black-Scholes delta from the "
               "premium's own implied vol in 0.30-0.65, theta decay <= 15% of the premium per day. Missing datum = no "
               "entry. Exits as v1 (2% trail). PAPER ONLY."),
    ), sr.StrategyDef(
        name=STRICT_OIG_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_step gate strict_oigreeks (B-1686), the single PAPER strategy",
        evidence="Paper forward test only; no intraday backtest possible yet (no free intraday option history).",
        notes=(RETIRED_V1 + "Was the active paper strategy (user 2026-11-23). Every 5 min 09:30-14:30 IST: top 3 index options by "
               "contracts traded per index, largest positive % change, not expiring today. Buy only if ALL hold: strict "
               "sentiment (index and NIFTY >= 0.25% in the trade direction, index beyond its day open, NIFTY breadth "
               ">= 1.5x, VIX up < 5% for a CE) AND OI rising with premium (long buildup) AND delta 0.30-0.65 AND theta "
               "<= 15% of premium per day. Missing datum = no entry. Exits: 2% stop from entry trailing the peak, out of "
               "top 3 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=V2_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_pick_v2 / _fno_momo_v2_skip (B-1714), the single PAPER strategy",
        evidence="Paper forward test only; replay on the per-minute View 6 tape (B-1687) once enough days exist.",
        notes=(RETIRED_V2 + "Every 5 min 09:30-14:30 IST, EVERY top-5 index option by "
               "contracts traded per index is checked; buy the one with the largest 15-min premium rise that passes ALL: "
               "not expiring today; strict sentiment (index and NIFTY >= 0.25% in the trade direction, index beyond its "
               "day open, NIFTY breadth >= 1.5x, VIX up < 5% for a CE); premium rising over 5 min AND 15 min, 1 h not "
               "falling, 5-min rise <= 10% (no chasing); long build-up (premium up with OI up; Kotak rows use OI change "
               "since first seen today); delta 0.35-0.65; >= 2 days to expiry; theta <= 15% of premium per day; IV <= "
               "1.25x the index's median IV. Missing datum = no entry. Exits: 2% stop trailing the peak, out of the top "
               "5 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=V3_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_pick_v3 / _fno_momo_v3_skip (B-1715), the single PAPER strategy",
        evidence="Paper forward test only; replay on the per-minute View 6 tape (B-1687) once enough days exist.",
        notes=(RETIRED_V3 + "Was the active paper strategy (user 2026-11-25: exits within 15 min, research-based). Every 5 min, in "
               "09:30-11:15 and 13:15-14:30 IST only (mid-day reversal zone skipped), EVERY top-5 index option by "
               "contracts traded is checked; buy the largest 5-min premium rise that passes ALL: not expiring today; "
               "strict sentiment (trend day); the index moved >= 0.05% in the trade direction over 5 min; premium up "
               "over 5 min but <= 10%; 15-min rise <= 20% (unknown does not block); premium >= Rs 20; delta 0.40-0.60; "
               "IV <= 1.25x the index median. OI recorded, not a gate. Exits: 2% stop trailing the peak, 15-min time "
               "stop, out of the top 5 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=V3B_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_pick_v3(allow_expiry=True) / _fno_momo_v3_skip (B-1717), the single PAPER strategy",
        evidence="Paper forward test only; replay on the per-minute View 6 tape (B-1687) once enough days exist.",
        notes=("THE active paper strategy (user 2026-11-25: include expiry-day contracts, the 2% max SL then trail "
               "caps the loss). As " + V3_TAG + " but expiring-today contracts are checked too. Every 5 min, in "
               "09:30-11:15 and 13:15-14:30 IST only, EVERY top-5 index option by contracts traded is checked; buy the "
               "largest 5-min premium rise that passes ALL: strict sentiment (trend day); the index moved >= 0.05% in "
               "the trade direction over 5 min; premium up over 5 min but <= 10%; 15-min rise <= 20% (unknown does not "
               "block); premium >= Rs 20; delta 0.40-0.60; IV <= 1.25x the index median. OI recorded, not a gate. "
               "Exits: 2% stop trailing the peak, 15-min time stop, out of the top 5 or sentiment flip, forced 15:15 "
               "IST. Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=V3B_T5_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS[1] (B-1718), paper twin of " + V3B_TAG,
        evidence="Paper forward test only, compared trade for trade with the 2% twin.",
        notes=("ACTIVE paper twin (user 2026-11-25: test a wider trail along with 2%, show both results). The SAME "
               "entry rule as " + V3B_TAG + "; the only difference is the trailing SL: 5% below the peak premium "
               "instead of 2%. All other exits identical (15-min time stop, out of the top 5, sentiment flip, forced "
               "15:15 IST). Net of 0.8% cost. PAPER ONLY."),
    ), sr.StrategyDef(
        name=V4_T12_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS[2] / _fno_momo_v4_skip (B-1728)",
        evidence="Paper forward test; B-1727 replay (docs/FNO_V3_ASSUMPTION_EVIDENCE.md) is the prior.",
        notes=("ACTIVE paper plan (user 2026-11-25: short moves only, quick entry, quick exit, single leg; B-1727 study). "
               "Every 5 min, in 09:30-11:15 and 13:15-14:30 IST only, every top-5 index option by contracts traded is "
               "checked; buy the largest 5-min premium change that passes ALL: strict sentiment (trend day); the index "
               "moved >= 0.05% AGAINST the trade direction over the last 5 min (a pullback on a trend day); premium "
               ">= Rs 20; delta 0.40-0.60; IV <= 1.25x the index median. Expiry-day contracts included. Exits: 12% stop trailing the peak, +12% profit target, 15-min time stop, out of the top 5 or sentiment flip, forced 15:15 IST. "
               "Evidence: B-1727 89-day 5-min replay, synthetic premiums, gap-aware stops: PF 1.05 (n=278) for 12%/12%, "
               "but the edge came from the thin FINNIFTY proxy and was unstable across halves. Net of 0.8% cost. "
               "PAPER ONLY."),
    ), sr.StrategyDef(
        name=V4_T5_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS[3] (B-1728), paper twin of " + V4_T12_TAG,
        evidence="Paper forward test, compared trade for trade with the 12% twin.",
        notes=("ACTIVE paper plan (user 2026-11-25: short moves only, quick entry, quick exit, single leg; B-1727 study). "
               "Every 5 min, in 09:30-11:15 and 13:15-14:30 IST only, every top-5 index option by contracts traded is "
               "checked; buy the largest 5-min premium change that passes ALL: strict sentiment (trend day); the index "
               "moved >= 0.05% AGAINST the trade direction over the last 5 min (a pullback on a trend day); premium "
               ">= Rs 20; delta 0.40-0.60; IV <= 1.25x the index median. Expiry-day contracts included. Exits: 5% stop trailing the peak, +12% profit target, 15-min time stop, out of the top 5 or sentiment flip, forced 15:15 IST. "
               "Evidence: B-1727 89-day 5-min replay, synthetic premiums, gap-aware stops: PF 1.05 (n=278) for 12%/12%, "
               "but the edge came from the thin FINNIFTY proxy and was unstable across halves. Net of 0.8% cost. "
               "PAPER ONLY."),
    ), sr.StrategyDef(
        name=V4NB_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS[4] / _fno_momo_v4_skip(breadth=False) (B-1744), twin of " + V4_T12_TAG,
        evidence="Paper forward test; B-1744 90-day replay row mood|no_breadth (docs/fno_view6_row_ablation.json).",
        notes=("ACTIVE paper twin (user 2026-11-26 'build both a and b'). As " + V4_T12_TAG + " but the strict mood "
               "check drops the breadth >= 1.5x part (index and NIFTY >= 0.25% with the trade, index past its open, "
               "VIX rise < 5% for CE still apply). Replay 16-Jul..25-Nov, synthetic premiums: PF 1.11 net (n=358, 74 "
               "days) vs 1.07 (n=284) live rule; edge FINNIFTY-led (NIFTY 0.76, BANKNIFTY 0.90). Net of 0.8% cost. "
               "PAPER ONLY."),
    ), sr.StrategyDef(
        name=V4NBW_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS[5] / _fno_momo_v4_skip(breadth=False, FNO_V4_WIDE_WINDOWS) (B-1744)",
        evidence="Paper forward test; B-1744 90-day replay row mood|no_breadth_no_windows.",
        notes=("ACTIVE paper twin (user 2026-11-26 'build both a and b'). As " + V4NB_TAG + " and entries allowed "
               "09:30-14:30 IST straight through (no 11:15-13:15 midday gap). Replay: PF 1.02 net (n=562, 78 days); "
               "first half 0.87, second half 1.10, so weaker and less stable than the breadth-only twin. Net of 0.8% "
               "cost. PAPER ONLY."),
    )]


RETIRED_X = ("RETIRED 2026-11-26, 0 paper trades (B-1732, user 'Yes implement': the pullback plan skips expiry-day "
             "contracts; replaced by the _noexp tag of the same rule). ")
NOEXP = {V4_T12_TAG: ("[2]", "1.21 (n=270), H1 1.16, H2 1.25"), V4_T5_TAG: ("[3]", "1.07 (n=293), H1 1.17, H2 1.01"),
         V4NB_TAG: ("[4]", "1.25 (n=343), H1 1.02, H2 1.36"), V4NBW_TAG: ("[5]", "1.11 (n=536), H1 0.77, H2 1.30")}


def _noexp_name(tag):
    return tag.replace("_alldte_0930to1430__", "_noexp_0930to1430__").replace("_alldte__", "_noexp__")


def build():
    """B-1732: the four pullback tags are retired and each gets a _noexp twin (expiry-day contracts skipped)."""
    import dataclasses
    out = []
    for d in _build_base():
        if d.name in NOEXP:
            idx, pf = NOEXP[d.name]
            out.append(dataclasses.replace(d, notes=RETIRED_X + d.notes))
            out.append(dataclasses.replace(
                d, name=_noexp_name(d.name),
                source="main.py FNO_MOMO_VARIANTS" + idx + " (B-1732), replaces " + d.name,
                evidence="Paper forward test; B-1732 90-day replay with expiry-day contracts skipped.",
                notes=("ACTIVE paper plan (user 2026-11-26 'Yes implement', B-1732). The same rule as " + d.name +
                       " except contracts expiring today are skipped (skipped_expiry_day). Replay 16-Jul..25-Nov, "
                       "synthetic premiums, net of 0.8% cost: PF " + pf + ". PAPER ONLY.")))
        else:
            out.append(d)
    out.append(sr.StrategyDef(
        name=ATMC_TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py FNO_MOMO_VARIANTS gate atmchain_v1 / _fno_momo_pick_atmc / _fno_atmc_skip (B-1757)",
        evidence="Paper forward test only; replay on the per-minute ATM-chain tape (B-1688) once enough days exist.",
        notes=("ACTIVE paper plan (user rule 'Single-leg option candidate universe', B-1757). Every 5 min 09:30-14:30 "
               "IST, EVERY index's ATM +-10 strike legs (CE and PE, nearest expiry, from the tape's cached chain, no "
               "new fetch) are checked; buy the single best leg across all indices by score (5-min premium change + "
               "15-min change / 3) that passes ALL: fresh quote (premium moved within 5 min, B-1750); >= 1000 "
               "contracts traded; index day direction confirms the type (CE: index and NIFTY up; PE: both down); "
               "premium up over 5 min AND 15 min; |delta| 0.35-0.65; IV not above the same-type ATM leg's IV. Exits: "
               "2% stop from entry trailing the peak, 15-min time stop, sentiment flip, frozen quote, forced 15:15 "
               "IST; never the most-active rank exit. Net of 0.8% cost. PAPER ONLY."),
    ))
    return out
