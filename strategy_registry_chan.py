"""Registers chan-research.yml run 38183172728 (2026-10-12 IST, 1d and 1h, cost 0.8%): 258 Chan (Algorithmic Trading) cells, one tag each.
Raw table docs/backtest_data/chan_research_run_38183172728.json.  Trades are overlapping signals (n is signal count, not a
non-overlapping portfolio), so a non-overlap re-run is owed before wiring; viability derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "chan_research_run_38183172728.json")
_REF = "chan-research.yml run 38183172728 (2026-10-12 IST, 1d/1h, cost 0.8%)"
_FN2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "chan_nonoverlap_run_38187474707.json")
_REF2 = "chan-nonoverlap.yml run 38187474707 (2026-10-12 IST, 1d/1h, cost 0.8%, strict FIFO one position per symbol per cell)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    rows = {}
    for fn, ref in ((_FN, _REF), (_FN2, _REF2)):
        try:
            for k, v in json.load(open(fn))["results"].items():
                rows[k] = (v, ref)
        except Exception:
            continue
    for tag, (r, REF) in rows.items():
        try:
            if tag in seen or r.get("pfnet") is None:
                continue
            seen.add(tag)
            tf = tag.split("__")[3]
            short = "__short__" in tag
            cat = sr.TradeCategory.SHORT_SELL if short else (sr.TradeCategory.SWING if tf == "1d" else sr.TradeCategory.BUY)
            hrs = float(r["avg_hold_bars"]) * sr.market_hours_per_bar(tf)
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING if tf == "1d" else sr.AssetClass.EQUITY_INTRADAY,
                categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pfgross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=hrs,
                    universe="NSE harness universe (full, chan-research shards)", run_ref=REF),
                source="scripts/chan_research.py",
                evidence=f"{REF}: PFnet {r['pfnet']}, gross {r.get('pfgross')}, win {r['win_pct']}%, n={r['n']} ({'non-overlapping FIFO' if 'nonovl' in tag else 'overlapping signals'}), avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Chan cell; ATR stop in every cell; overlapping signals so non-overlap re-run owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
