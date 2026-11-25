"""B-1676 (user 2026-11-23): PAPER-only most-active index option momentum, run in-process on the View 6 (B-1675) data.
No result yet, so metrics=None (viability can't be judged; never wired). Real-money wiring needs the user's yes plus
pooled PFnet > 1.00. Per-category coverage: options (single-leg index long CE/PE) only."""
import strategy_registry as sr

TAG = "fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1"
STRICT_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti__long_opt__5m__trail2__v1"  # B-1677
OIG_TAG = "fno_mostactive_momo__top3_max_gain_oigreeks__long_opt__5m__trail2__v1"  # B-1681
STRICT_OIG_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti_oigreeks__long_opt__5m__trail2__v1"  # B-1686
V2_TAG = "fno_mostactive_momo__mtfmomo_oibuild_greeks_ivrel__long_opt__5m__trail2__v1"  # B-1714
V3_TAG = "fno_mostactive_momo__fast5m_idxconfirm_delta_ivrel__long_opt__5m__trail2_hold15__v1"  # B-1715: the ONE active
RETIRED_V2 = ("RETIRED 2026-11-25 before deploy, 0 trades (B-1715, user: trades exit within 15 min, do not wait for "
              "1 h; research first): replaced by the fast 5-15 min plan. ")
RETIRED_V1 = ("RETIRED 2026-11-25 (B-1714, user: research OI/Greeks/% change and plan the paper entry): 0 entries in "
              "its run (one largest-day-% candidate per scan, OI build blank on Kotak rows). ")
RETIRED = "RETIRED 2026-11-23 (B-1686, user: one strategy = strict sentiment + OI/Greeks): no new entries. "


def build():
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
        notes=("THE active paper strategy (user 2026-11-25: exits within 15 min, research-based). Every 5 min, in "
               "09:30-11:15 and 13:15-14:30 IST only (mid-day reversal zone skipped), EVERY top-5 index option by "
               "contracts traded is checked; buy the largest 5-min premium rise that passes ALL: not expiring today; "
               "strict sentiment (trend day); the index moved >= 0.05% in the trade direction over 5 min; premium up "
               "over 5 min but <= 10%; 15-min rise <= 20% (unknown does not block); premium >= Rs 20; delta 0.40-0.60; "
               "IV <= 1.25x the index median. OI recorded, not a gate. Exits: 2% stop trailing the peak, 15-min time "
               "stop, out of the top 5 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    )]
