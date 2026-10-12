"""Registers island-validation.yml run 38221645245 (2026-10-12 IST, 1d, cost 0.8%): strict-FIFO non-overlap (`nonovl__v2`) and
in-sample/out-of-sample (`segis__v2` / `segoos__v2`) island-reversal cells, long and short, one tag each (B-815).
Raw table docs/backtest_data/island_oos_1d_run_38221645245.json (includes pfnet_ex_top5 and by_year).
Tags already registered by strategy_registry_island (the `__v1` full-sample ones) are skipped.  Research-only, entry_fn=None;
viability is derived at read time from PFnet vs PFNET_LIVE_FLOOR, nothing wired live."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "island_oos_1d_run_38221645245.json")
_REF = "island-validation.yml run 38221645245 (2026-10-12 IST, 1d, cost 0.8%, non-overlap + IS/OOS split)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_FN))
        cells = d["cells"]
    except Exception:
        return out
    uni = "NSE full universe (%s with data of %s listed)" % (d.get("universe_with_data"), d.get("universe_listed"))
    for tag, r in cells.items():
        try:
            if tag in seen:
                continue
            seen.add(tag)
            short = "__short__" in tag
            part = "segis" if "__segis__" in tag else "segoos" if "__segoos__" in tag else "nonovl"
            yrs = ",".join(f"{y}:{v['pfnet']}(n{v['n']})" for y, v in (r.get("by_year") or {}).items())
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                                   universe=uni, run_ref=_REF),
                source="scripts/island_validation.py",
                evidence=f"{_REF}, {part}: PFnet {r['pfnet']} (ex-top5 {r.get('pfnet_ex_top5')}), gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; by-year PFnet {yrs}; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
                notes=f"Island-reversal {part} cell (one position per symbol, strict FIFO; segis/segoos = entry-date split); ATR stop in every trade; research-only, entry_fn=None, nothing wired (B-815). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
