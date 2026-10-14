"""Registers macddiv-nonoverlap.yml run 38277559172 (2026-10-12 IST, 15m, cost 0.8%, strict FIFO one position per symbol per cell, IS/OOS split, sweep long+short).
Raw table docs/backtest_data/macddiv_nonovl_15m_run_38277559172.json. Every tag (pooled, _segis, _segoos) is its own strategy; direction is its own tag.
Viability derived at read time from PFnet vs PFNET_LIVE_FLOOR; nothing wired (no live entry path). B-812."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "macddiv_nonovl_15m_run_38277559172.json")
_REF = "macddiv-nonoverlap.yml run 38277559172 (2026-10-12 IST, 15m, cost 0.8%, strict FIFO, IS/OOS split)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_FN))
        res = d["results"]
    except Exception:
        return out
    for tag, r in res.items():
        if tag in seen:
            continue
        seen.add(tag)
        short = "__short__" in tag
        seg = "IS segment" if "_segis" in tag else ("OOS segment" if "_segoos" in tag else "pooled")
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.BUY,), timeframe="15m",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * 0.25,
                               universe=f"NSE full universe ({d.get('fetched')} fetched)", run_ref=_REF),
            source="scripts/macd_divergence_research.py",
            evidence=(f"{_REF}: [{seg}] PFnet {r['pfnet']} (trim1 {r.get('pfnet_trim1')}, trim5 {r.get('pfnet_trim5')}), gross {r['pf_gross']}, "
                      f"win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} 15m bars, avg_net {r['avg_net_ret_pct']}%, "
                      f"max_trade {r.get('max_trade_net_ret_pct')}%, raw_signals_before_fifo={r.get('raw_signal_trades_before_fifo')}; "
                      f"exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}; by-year not measured"),
            notes=(f"macddiv 15m non-overlap sweep ({seg}); each of pooled/_segis/_segoos is its own strategy. avg_held_hrs = bars x 0.25 (15m bars, wall-clock). "
                   "ATR stop in every trade. Viability derived vs PFNET_LIVE_FLOOR; nothing wired. 5m/1d still owed (B-812).")))
    return out
