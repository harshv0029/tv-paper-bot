"""Registers portfolio-overlay-research.yml run 38193834873 (2026-10-12 IST, 1d, cost 0.8%): pfovl__* overlay cells (792 rows).
Raw: docs/backtest_data/pfovl_run_38193834873.json (+ _table.txt) kept in full. Research-only (entry_fn=None).
CAVEAT: overlapping-signal harness cells; calendar-slice (year/month/passtrade) filters are data-mined. Any viable-looking cell needs strict non-overlap FIFO + IS/OOS before wiring."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "pfovl_run_38193834873.json")
_RUN = "portfolio-overlay-research.yml run 38193834873 (2026-10-12 IST, 1d, cost 0.8%)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        with open(_FN) as fh:
            rows = json.load(fh)["rows"]
    except Exception:
        return out
    for r in rows:
        tag = r["tag"]
        if tag in seen:
            continue
        seen.add(tag)
        short = "__short__" in tag
        extra = {k: r[k] for k in ("final_mult", "max_dd_pct", "expectancy_pct", "pfnet_ci95_lo", "pfnet_ci95_hi", "kept_pct") if k in r}
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe="1d",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                               universe="NSE full universe + ETFs (2348 with data of 2688)", run_ref=_RUN),
            source="scripts/portfolio_overlay_research.py",
            evidence=f"{_RUN}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, {json.dumps(extra, separators=(',', ':'))}; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
            notes="Overlay cell from an overlapping-signal harness; calendar-slice (year/month/passtrade) filters are data-mined. Strict non-overlap FIFO + IS/OOS owed before any wiring (B-819). Research-only: real-money gate stays closed. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
    return out
