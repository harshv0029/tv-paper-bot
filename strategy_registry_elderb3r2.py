"""Registers elder-batch3-research.yml run 38211452647 (2026-10-12 IST, 1d, cost 0.8%).  UNIVERSE CAVEAT: this run used NIFTY200 + 182 ETFs
(14392 symbols fetched over family slots, NOT the full 8064-symbol NSE universe), so the standing full-universe rule applies: a full-universe
rerun is owed before ANY wiring.  The same cells were registered earlier from run 38169625565 (strategy_registry_elderb3.py, also NIFTY200+ETF, an earlier data window), and
this rerun printed different numbers (e.g. div_class kb_oscrsi PFnet 0.958 then vs 2.433 now), so every tag here carries the suffix
`_rn38211452647` in its params field (naming immutability: a new run is a new tag, the old one stays untouched).  The jump between
two runs of the identical cells on the same universe is itself a red flag (data-window/fetch sensitivity) to root-cause before trust.
All 492 rows registered research-only (entry_fn=None) with real metrics.  PFnet gross may be None in raw (kept as 0.0 here, raw JSON has the
truth); 9 rows have PFnet None (n=1-2, no losing trade) and are stored as pfnet 0.0 (fails closed, NOT a real zero; see evidence).
Standouts owed follow-up: osc__div_class long kb_oscrsi (2.433, n=10676) and kb_oscmacdh (2.398, n=11073): short mirror, IS/OOS, FIFO, other
candle sizes.  breadth__* cells have n=2-6: not evidence.  Raw data: docs/backtest_data/elder_batch3_n200etf_38211452647_results.json (+ _table.txt)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_batch3_n200etf_38211452647_results.json")
_REF = "elder-batch3-research.yml run 38211452647 (2026-10-12 IST, 1d, cost 0.008, universe NIFTY200 + 182 ETFs, NOT full universe)"
SUFFIX = "_rn38211452647"


def tag_for(raw_tag):
    return raw_tag[:-len("__v1")] + SUFFIX + "__v1" if raw_tag.endswith("__v1") else raw_tag + SUFFIX


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = tag_for(r["tag"])
            if tag in seen:
                continue
            seen.add(tag)
            intraday = "__5m__" in tag
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else (sr.TradeCategory.BUY if intraday else sr.TradeCategory.SWING)
            hrs = float(r["avg_hold_bars"]) * (5.0 / 60.0 if intraday else sr.TRADING_HOURS_PER_DAY)
            undefined = r.get("pfnet") is None
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY if intraday else sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="5m" if intraday else "1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=0.0 if undefined else float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0),
                    win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                    avg_held_hrs=hrs,
                    universe="NIFTY200 + 182 ETFs (14392 symbols fetched over family slots), NOT the full NSE universe; cost 0.008 round trip", run_ref=_REF),
                source="scripts/elder_batch3_research.py",
                evidence=f"{_REF}: source tag {r['tag']}; PFnet {r['pfnet']}{' (undefined in raw, stored 0.0, n too small)' if undefined else ''} (gross {r.get('pf_gross')}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Elder batch-3 rerun cell (orb/struct/chan/osc/breadth) on NIFTY200+ETF universe only; full-universe rerun owed before any wiring (B-863). Overlapping signals inflate n; FIFO non-overlap + IS/OOS and opposite-direction/candle-size sweeps owed. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
