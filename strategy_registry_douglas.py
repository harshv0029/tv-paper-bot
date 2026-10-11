"""Registers every row of douglas-trade-mgmt-research.yml run 38174269343 (2026-10-12 IST, 1d, cost 0.8%): trademgmt_entry (228) and
trademgmt_exit (252) cells, from the committed merged results docs/backtest_data/douglas_trademgmt_run_38174269343.json (raw table
alongside; MFE/MAE and losers-reached-R stats are kept in the JSON/table).  Universe: 5376 symbols listed, 4699 fetched with data.
Each tag is its own row, viability derived at read time from pfnet, nothing wired.  Existing tags are skipped.  Hold is in daily bars."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "douglas_trademgmt_run_38174269343.json")
_REF = "douglas-trade-mgmt-research.yml run 38174269343 (2026-10-12 IST, 1d, cost 0.8%, 5376 listed / 4699 fetched)"


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
                    universe="5376 listed / 4699 fetched (broad NSE+ETF harness universe)", run_ref=_REF),
                source="scripts/douglas_trade_mgmt_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (gross {r.get('pf_gross')}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%, MFE {r.get('avg_mfe_r')}R MAE {r.get('avg_mae_r')}R, losers reaching 0.5R {r.get('losers_reached_half_r_pct')}% / 1R {r.get('losers_reached_1r_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Douglas/Elder trade-management cell; main.py replay + exit port owed before wiring; SL is part of every cell (atr stop). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
