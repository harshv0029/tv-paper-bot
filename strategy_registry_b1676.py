"""B-1676 (user 2026-11-23): PAPER-only most-active index option momentum, run in-process on the View 6 (B-1675) data.
No result yet, so metrics=None (viability can't be judged; never wired). Real-money wiring needs the user's yes plus
pooled PFnet > 1.00. Per-category coverage: options (single-leg index long CE/PE) only."""
import strategy_registry as sr

TAG = "fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1"


def build():
    return [sr.StrategyDef(
        name=TAG, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe="5m",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=None,
        source="main.py _fno_momo_step (B-1676), PAPER forward test on NSE most-active index options",
        evidence="Paper forward test only (fno_momo_paper_trades, /fno-momo-paper); no backtest yet.",
        notes=("Every 5 min 09:30-14:30 IST: top 3 index options by contracts traded per index, largest positive "
               "% change; enter long if CE: index and NIFTY up / PE: both down. Exits: trailing SL 2% of premium from "
               "peak, out of top 3 or sentiment flip, forced 15:15 IST. Net of 0.8% cost. PAPER ONLY."),
    )]
