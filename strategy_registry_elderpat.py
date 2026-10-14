"""Registers elder-patterns-research.yml run 38190581834 (2026-10-12 IST, 1d, cost 0.8%, harness universe 10752 listed / 9399 with data).
Raw: docs/backtest_data/elder_patterns_run_38190581834.json (+ _table.txt), all 252 rows kept.  228 tags already registered from run 38148955837
(strategy_registry_elderpat_minsweep.py, identical numbers on the checked tag) are skipped, never renamed; the 24 new tags (trendline__tl_break_mm
measured-move target B-623, consol__edge_bounce_srtight tight-stop S/R B-607) are registered here, long and short each.
Viability derived at read time; nothing wired.  avg_hold in daily bars."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_patterns_run_38190581834.json")
_REF = "elder-patterns-research.yml run 38190581834 (2026-10-12 IST, 1d, cost 0.8%)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tag.split("__")[3],
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="NSE harness universe (10752 listed, 9399 with data)", run_ref=_REF),
                source="scripts/elder_patterns_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r.get('pf_gross')}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Elder-pattern cell, ATR stop; overlapping signals likely (n far above days x symbols), non-overlap re-run owed before any wiring; main.py replay owed. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
