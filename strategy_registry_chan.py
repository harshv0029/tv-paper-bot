"""Registers every tag of chan-research.yml run 38142463808 (2026-10-11 IST, 258 tags, NIFTY200 + ETF
universe, 0.8% cost) from the committed raw TSV.
Each tag is its own registry row (pass or fail).  Viability is derived at read time from pfnet (PFNET_LIVE_FLOOR)."""
import csv
import os

import strategy_registry as sr

_TSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                    "chan_run_38142463808.tsv")
_REF = "chan-research.yml run 38142463808 (2026-10-11 IST, NIFTY200 + 182 ETFs only, NOT full universe, cost 0.8%)"


def build():
    out = []
    try:
        rows = list(csv.DictReader(open(_TSV), delimiter="\t"))
    except Exception:
        return out
    for r in rows:
        tag = r["tag"]
        short = "__short__" in tag
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
            timeframe=tag.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=float(r["pfnet_net"]), pfgross=float(r["pfnet_gross"] or 0.0), win_rate_pct=float(r["win_pct"]),
                n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_days"]) * sr.TRADING_HOURS_PER_DAY,
                universe="nifty200_plus_etf", run_ref=_REF),
            source="scripts/chan_research.py",
            evidence=f"{_REF}: PFnet {r['pfnet_net']}, win {r['win_pct']}%, n={r['n']}, held {r['avg_hold_days']}d; exits {r['exits']}",
            notes="Chan (B-424..B-452) research cell, no live path; full-universe re-run owed before any go/no-go. Viability derived from PFnet vs PFNET_LIVE_FLOOR at read time; "
                  "being registered viable does not by itself create a live path (only wired tags trade).",
        ))
    return out
