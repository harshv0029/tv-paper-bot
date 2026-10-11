"""Registers every osc/struct tag of elder-batch3-research.yml run 38169625565 (2026-10-11 IST, 1d, cost 0.8%) from the
committed merged-shard TSV docs/backtest_data/elder_batch3_osc_struct_run_38169625565.tsv (4 shards summed; nothing trimmed).
Universe: NIFTY200-restricted + 182 ETFs (the run log printed the restriction line), about 14.4k of 16.1k symbol-slots fetched, NOT the full NSE universe: a full-universe re-run is
owed before wiring.  Each tag is its own row, viability derived at read time from pfnet, nothing is wired.  Hold is in daily bars.
The ORB (5m) and sizing families of the same run all failed (ORB PFnet 0.13-0.19, sizing every method negative) and are logged
in the backlog; their raw tables were not saved."""
import csv
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_batch3_osc_struct_run_38169625565.tsv")
_REF = "elder-batch3-research.yml run 38169625565 (2026-10-11 IST, 1d, cost 0.8%, NIFTY200+ETF slots, not full NSE)"


_MERGED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_batch3_merged_run_38169625565.json")


def _merged_rows():
    try:
        return json.load(open(_MERGED))["rows"]
    except Exception:
        return []


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = list(csv.DictReader(open(_FN), delimiter="\t"))
    except Exception:
        return out
    rows = list(rows) + [dict(tag=x["tag"], n=x["n"], win_pct=x["win_pct"], pfnet=x["pfnet"], pfgross=x.get("pf_gross") if x.get("pf_gross") is not None else "None",
                              avg_hold_bars=x["avg_hold_bars"], exits=json.dumps(x.get("exit_reasons"), separators=(",", ":")))
                         for x in _merged_rows() if x["tag"].split("__")[0] in ("chan", "breadth", "orb") and x.get("pfnet") is not None]
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen or tag == "tag" or r["pfnet"] in ("", "None"):
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            g = r["pfgross"]
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=(0.0 if g in ("", "None") else float(g)),
                    win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                    avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="NIFTY200-restricted + ETF slots (harness printed the restriction line; ~14.4k of 16.1k symbol-slots fetched), not full NSE", run_ref=_REF),
                source="scripts/elder_batch3_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (gross {g}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars; exits {r['exits']}",
                notes="Elder batch-3 oscillator/structure cell on a NIFTY200+ETF list; full-universe re-run + main.py replay owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
