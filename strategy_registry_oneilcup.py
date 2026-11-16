"""Registers oneil-research.yml run 38193479637 (2026-10-12 IST, cost 0.8%): O'Neil cup-and-handle cells, 1d (1218 cells) and 1w (1022 cells).
Raw tables docs/backtest_data/oneil_{1d,1w}_run_38193479637.{tsv,json} kept in full. Research-only (entry_fn=None); viability derived at read time.
avg_hold unit: 1d = trading days, 1w = weeks (x5 trading days) -> avg_held_hrs = days * TRADING_HOURS_PER_DAY."""
import csv
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUN = "oneil-research.yml run 38193479637 (2026-10-12 IST, cost 0.8%)"
_RUN_NEW = "oneil-research.yml run 43770029152 (2026-11-16 IST, cost 0.8%)"
# Newest run first (B-783 rerun 2026-11-16 IST): a tag takes the latest run's metrics; the old run fills any gap.
_SRCS = tuple((f"oneil_base_{tf}_cells_run_43770029152.tsv", tf, _RUN_NEW) for tf in ("1d", "1w")) + tuple(
    (f"oneil_{tf}_run_38193479637.tsv", tf, _RUN) for tf in ("1d", "1w"))


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, tf, run in _SRCS:
        try:
            with open(os.path.join(_DIR, fn)) as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
        except Exception:
            continue
        for r in rows:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            short = r["dir"] == "short"
            hold = float(r["avg_hold"])
            days = hold * 5 if tf == "1w" else hold
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pfgross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_hrs=days * sr.TRADING_HOURS_PER_DAY,
                                   universe="NSE full universe (symbols with data)", run_ref=run),
                source="scripts/oneil_research.py",
                evidence=f"{run}: PFnet {r['pfnet']}, gross {r['pfgross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold']} {r['avg_hold_unit']}, avg_net {r['avg_net_pct']}%, max trade {r['max_trade_net_pct']}%; exits {r['exit_reasons_json']}",
                notes="O'Neil cup-and-handle cell (overlapping signals, ATR stop in every trade; stops lose ~-8..-10%, timeouts carry the profit). Non-overlap FIFO + IS/OOS owed before wiring (B-818). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
    return out
