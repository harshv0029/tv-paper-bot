"""Registers macddiv-nonoverlap.yml run 38218870434 (2026-10-12 IST, 1h, cost 0.8%, strict FIFO, IS/OOS split, sweep long+short).
Raw table docs/backtest_data/macddiv_oos_1h_run_38218870434.json. Every tag (pooled, _segis, _segoos) is its own strategy with its own
numbers; none is pooled with another. Keep rule: n>=30. Research-only (entry_fn=None); viability derived at read time; nothing wired.
Fields NOT measured by this run: ex-top5 PFnet, by-year PFnet, trim1."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "macddiv_oos_1h_run_38218870434.json")
_REF = "macddiv-nonoverlap.yml run 38218870434 (2026-10-12 IST, 1h, cost 0.8%, strict FIFO, IS/OOS split)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_FN))
        res = d["results"]
    except Exception:
        return out
    for tag, r in res.items():
        if tag in seen or r.get("n", 0) < 30:
            continue
        seen.add(tag)
        short = "__short__" in tag
        seg = "IS segment" if "_segis" in tag else ("OOS segment" if "_segoos" in tag else "pooled")
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.BUY,), timeframe="1h",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_bars"]),
                               universe=f"NSE full universe ({d.get('fetched')} fetched)", run_ref=_REF),
            source="scripts/macd_divergence_research.py",
            evidence=(f"{_REF}: [{seg}] PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, "
                      f"avg_net {r['avg_net_ret_pct']}%, raw_signals_before_fifo={r.get('raw_signal_trades_before_fifo')}; "
                      f"exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}; ex-top5/by-year not measured"),
            notes=(f"macddiv 1h IS/OOS sweep ({seg}); each of pooled/_segis/_segoos is its own strategy. Long cells that clear the floor pooled "
                   "or IS collapse OOS (B-814). ATR stop in every trade. Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
    return out
