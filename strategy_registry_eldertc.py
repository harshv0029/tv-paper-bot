"""Registers elder-trend-context-research.yml run 38209280422 (2026-10-12 IST, 1d, cost 0.8%, universe 8064 symbols, 7053 fetched with data).
All 210 tags (ma, regime, osc families; long and short) registered as research-only cells (entry_fn=None) with real metrics, none clears the
PFnet floor (best 0.984).  Raw data kept in full: docs/backtest_data/elder_trend_context_38209280422_results.json (+ _table.txt).
Bidirectional note: osc__open_gap_fade is short-only here, its long mirror is owed (B-862).  Hold is in daily bars."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_trend_context_38209280422_results.json")
_REF = "elder-trend-context-research.yml run 38209280422 (2026-10-12 IST, 1d, cost 0.008, universe 8064 / 7053 fetched)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen or r.get("pfnet") is None:
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="8064 symbols, 7053 fetched with data (full NSE universe file), cost 0.008 round trip", run_ref=_REF),
                source="scripts/elder_trend_context_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (gross {r.get('pf_gross')}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Elder trend/regime/MA-system/context cell (SL is part of every cell; overlapping signals inflate n; non-overlap FIFO + IS/OOS owed before wiring). Opposite-direction mirror owed where only one side was run (B-862). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
