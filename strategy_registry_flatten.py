"""Registers intraday-flatten-rerun.yml run 38185672296 (B-792): intraday cells re-run with a forced 15:15 IST flatten, tag `<old>_fl1515__v2`.
Raw table docs/backtest_data/flatten_rerun_run_38185672296.json.  Research cells only; viability derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "flatten_rerun_run_38185672296.json")
_REF = "intraday-flatten-rerun.yml run 38185672296 (2026-10-12 IST, forced flatten 15:15 IST, cost 0.8%)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["results"]
    except Exception:
        return out
    for tag, r in rows.items():
        try:
            if tag in seen or r.get("pfnet") is None:
                continue
            seen.add(tag)
            short = "__short__" in tag
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.BUY,),
                timeframe=tag.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pfgross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_hrs=float(r.get("avg_held_hrs") or 0.0),
                    universe="NSE full universe (flatten-rerun shards)", run_ref=_REF),
                source="scripts/intraday_flatten_rerun.py",
                evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r.get('pfgross')}, win {r['win_pct']}%, n={r['n']}, avg_hold {r.get('avg_held_bars')} bars, avg_net {r.get('avg_net_pct')}%; source {r.get('source_tag')} orig {json.dumps(r.get('orig'), separators=(',', ':'))}; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Flatten re-run of an intraday cell; ATR stop in every cell; overlapping signals as in source run. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
