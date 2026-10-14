"""Registers island-validation.yml run 38192367677 (2026-10-12 IST, 1d, cost 0.8%): island-reversal cells, one tag each.
Raw table docs/backtest_data/island_run_38192367677.json (includes pfnet_ex_top5 and by_year). Viability derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "island_run_38192367677.json")
_REF = "island-validation.yml run 38192367677 (2026-10-12 IST, 1d, cost 0.8%)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        cells = json.load(open(_FN))["cells"]
    except Exception:
        return out
    for tag, r in cells.items():
        if tag in seen:
            continue
        seen.add(tag)
        short = "__short__" in tag
        yrs = ",".join(f"{y}:{v['pfnet']}" for y, v in (r.get("by_year") or {}).items())
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe="1d",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                               universe="NSE full universe (2351 with data of 2688 listed)", run_ref=_REF),
            source="scripts/island_validation.py",
            evidence=f"{_REF}: PFnet {r['pfnet']} (ex-top5 {r.get('pfnet_ex_top5')}), gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; by-year PFnet {yrs}; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
            notes="Island-reversal cell; ATR stop in every trade. By-year PFnet shows recent decay in 2026 (long cells ~0.2): IS/OOS and non-overlap check owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
    return out
