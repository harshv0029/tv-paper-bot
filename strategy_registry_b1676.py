"""B-1676 (user 2026-11-23): PAPER-only most-active index option momentum, run in-process on the View 6 (B-1675) data.
No result yet, so metrics=None (viability can't be judged; never wired). Real-money wiring needs the user's yes plus
pooled PFnet > 1.00. Per-category coverage: options (single-leg index long CE/PE) only."""
import strategy_registry as sr

TAG = "fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1"
STRICT_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti__long_opt__5m__trail2__v1"  # B-1677
OIG_TAG = "fno_mostactive_momo__top3_max_gain_oigreeks__long_opt__5m__trail2__v1"  # B-1681
STRICT_OIG_TAG = "fno_mostactive_momo__top3_max_gain_strictsenti_oigreeks__long_opt__5m__trail2__v1"  # B-1686: the ONE active
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
        notes=("THE active paper strategy (user 2026-11-23). Every 5 min 09:30-14:30 IST: top 3 index options by "
               "contracts traded per index, largest positive % change, not expiring today. Buy only if ALL hold: strict "
               "sentiment (index and NIFTY >= 0.25% in the trade direction, index beyond its day open, NIFTY breadth "
               ">= 1.5x, VIX up < 5% for a CE) AND OI rising with premium (long buildup) AND delta 0.30-0.65 AND theta "
               "<= 15% of premium per day. Missing datum = no entry. Exits: 2% stop from entry trailing the peak, out of "
               "top 3 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    )]
