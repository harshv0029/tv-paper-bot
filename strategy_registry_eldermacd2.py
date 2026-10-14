"""Registers elder-macd-dirgap-research.yml run 38208431466 (2026-10-12 IST, 1d, cost 0.8%, 7059 symbols fetched summed over families), the re-run of
run 38177547622 (7049 fetched).  Raw data kept in full: docs/backtest_data/elder_macd_dirgap_38208431466_results.json (+ _table.txt).
All 120 of its tags (macd, dirsys, gaps families, long and short) were already registered, so under the never-overwrite rule this builder adds only
tags not yet present (0 today) and the re-run is kept as a reproduction record (see STRATEGY_LEARNINGS.md and B-850).
Research-only (entry_fn=None); viability derived at read time.  Hold is in daily bars."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_macd_dirgap_38208431466_results.json")
_REF = "elder-macd-dirgap-research.yml run 38208431466 (2026-10-12 IST, 1d, cost 0.8%, 7059 fetched summed over families)"


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
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="7059 fetched summed over families (broad NSE+ETF harness universe)", run_ref=_REF),
                source="scripts/elder_macd_dirgap_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (gross {r.get('pf_gross')}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%, MFE {r.get('avg_mfe_r')}R MAE {r.get('avg_mae_r')}R, losers reaching 0.5R {r.get('losers_reached_half_r_pct')}% / 1R {r.get('losers_reached_1r_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Elder MACD/directional-system/gap cell (overlapping signals inflate n, esp. macd__ and dirsys__ cells with n up to 250k; non-overlap FIFO + IS/OOS owed before wiring, B-850); SL is part of every cell. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
