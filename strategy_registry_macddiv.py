"""Registers macd-divergence-research.yml run 38188472624 (2026-10-12 IST, 15m/1h/1d, cost 0.8%): 108 macddiv cells, one tag each.
Raw table docs/backtest_data/macddiv_run_38188472624.json.  Trades are overlapping signals (n is signal count, not a
non-overlapping portfolio), so a non-overlap re-run is owed before wiring; viability derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "macddiv_run_38188472624.json")
_REF = "macd-divergence-research.yml run 38188472624 (2026-10-12 IST, 15m/1h/1d, cost 0.8%)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            tf = tag.split("__")[3]
            short = "__short__" in tag
            cat = sr.TradeCategory.SHORT_SELL if short else (sr.TradeCategory.SWING if tf == "1d" else sr.TradeCategory.BUY)
            hrs = float(r["avg_hold_bars"]) * (sr.TRADING_HOURS_PER_DAY if tf == "1d" else 1.0)
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING if tf == "1d" else sr.AssetClass.EQUITY_INTRADAY,
                categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_hrs=hrs,
                    universe="NSE harness universe (full, macddiv shards)", run_ref=_REF),
                source="scripts/macd_divergence_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r.get('pf_gross')}, win {r['win_pct']}%, n={r['n']} (overlapping signals), avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="MACD divergence cell; ATR stop in every cell; overlapping signals so non-overlap (FIFO) re-run owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
