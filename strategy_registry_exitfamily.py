"""Registers every tag of exit-family-research.yml run 38140914889 (2026-10-11 IST, daily/5y, full
universe, 0.8% cost, real main.py/entry fns with seven exit families) from the committed raw TSV.
Each tag is its own registry row (pass or fail). pfgross was not printed by the run (0.0 = not
recorded, never guessed). Viability is derived at read time from pfnet (PFNET_LIVE_FLOOR)."""
import csv
import os

import strategy_registry as sr

_TSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                    "exit_family_run_38140914889.tsv")
_REF = "exit-family-research.yml run 38140914889 (2026-10-11 IST, daily/5y, full universe, cost 0.8%)"


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
                pfnet=float(r["pfnet_net"]), pfgross=0.0, win_rate_pct=float(r["win_pct"]),
                n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_days"]) * sr.TRADING_HOURS_PER_DAY,
                universe="full_2680", run_ref=_REF),
            source="scripts/exit_family_research.py (real main.py entry fn + research exit family)",
            evidence=f"{_REF}: PFnet {r['pfnet_net']}, win {r['win_pct']}%, n={r['n']}, held {r['avg_hold_days']}d; exits {r['exits(reason:count:pfnet)']}",
            notes="B-529/B-538/B-493/B-740 exit-family cell. Viability derived from PFnet vs PFNET_LIVE_FLOOR at read time; "
                  "being registered viable does not by itself create a live path (only wired tags trade).",
        ))
    return out
