"""Registers macddiv-nonoverlap.yml run 38192366174 (2026-10-12 IST, 1h, cost 0.8%, strict FIFO one position per symbol per cell).
Raw table docs/backtest_data/macddiv_nonovl_run_38192366174.json. Viability derived at read time; nothing wired (no live entry path)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "macddiv_nonovl_run_38192366174.json")
_REF = "macddiv-nonoverlap.yml run 38192366174 (2026-10-12 IST, 1h, cost 0.8%, strict FIFO)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        res = json.load(open(_FN))["results"]
    except Exception:
        return out
    for tag, r in res.items():
        if tag in seen:
            continue
        seen.add(tag)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(sr.TradeCategory.BUY,), timeframe="1h",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]),
                               universe="NSE full universe (2483 fetched)", run_ref=_REF),
            source="scripts/macd_divergence_research.py",
            evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']} (non-overlapping FIFO, {r['raw_signal_trades_before_fifo']} raw signals), avg_hold {r['avg_hold_bars']} bars, avg_net {r['avg_net_ret_pct']}%; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
            notes="Non-overlap re-run of the overlapping macddiv 1h long cell (B-812). ATR stop in every trade. Viability derived from PFnet vs PFNET_LIVE_FLOOR; live wiring owed (needs 1h entry path, short mirror already registered)."))
    return out
