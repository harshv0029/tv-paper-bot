"""Registers lunar-sweep.yml run 38275906669 (2026-10-12 IST, 1d only, cost 0.8%): every lunar full/new/quarter-placebo cell,
long, short and pooled pair (B-112). Raw table docs/backtest_data/lunar_1d_run_38275906669.json (all columns incl exit_reasons_json).
Research-only, entry_fn=None; viability is derived at read time from PFnet vs PFNET_LIVE_FLOOR, nothing wired live."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "lunar_1d_run_38275906669.json")
_REF = "lunar-sweep.yml run 38275906669 (2026-10-12 IST, 1d, cost 0.8%, full NSE universe)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        cells = json.load(open(_FN))["cells"]
    except Exception:
        return out
    for r in cells:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            d = r["dir"]
            cat = {"short": sr.TradeCategory.SHORT_SELL, "bidirectional": sr.TradeCategory.BIDIRECTIONAL}.get(d, sr.TradeCategory.SWING)
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pfgross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold"]) * sr.TRADING_HOURS_PER_DAY,
                                   universe="NSE full universe", run_ref=_REF),
                source="scripts/lunar_sweep.py",
                evidence=f"{_REF}, {r['variant']} {d}: PFnet {r['pfnet']}, gross {r['pfgross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold']} {r['avg_hold_unit']}, avg_net {r['avg_net_pct']}%, max trade {r['max_trade_net_pct']}%; exits {json.dumps(r['exit_reasons_json'], separators=(',', ':'))}",
                notes="Lunar-phase cell (Meeus moon phase; quarter = placebo); ATR stop in every trade; 1d only, other candle sizes owed; research-only, entry_fn=None, nothing wired (B-112). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
