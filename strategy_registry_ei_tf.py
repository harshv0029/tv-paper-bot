"""Registers elder-indicators-research.yml intraday/4h runs (B-579 B-590 family: ema13, roc, ema_gate, stoch_filter,
triple_screen, adx_bell, ...). Harness scripts/elder_indicators_research.py (research re-implementation, not main.py
functions), full universe via main._load_nse_universe_from_file(), 0.8% cost. Raw rows rebuilt from the merge-job log
(artifact download 403): docs/backtest_data/elder_indicators_<tf>_run_<id>.json. The merge table prints no gross PF,
so pfgross is 0.0 (not measured, never guessed). Every tag pass or fail; tags already registered are skipped.
Viability derived at read time; nothing wired from here. avg_hold in bars of the tag's own timeframe."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "elder_indicators_*_run_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        ref, uni = d["run_ref"], d["universe"]
        for r in d.get("rows", []):
            try:
                tag = r["tag"]
                if tag in seen:
                    continue
                seen.add(tag)
                tf = tag.split("__")[3]
                short = "__short__" in tag
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                    categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
                    timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=0.0, win_rate_pct=float(r["win_pct"]),
                                       n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                                       avg_held_hrs=float(r["avg_hold_bars"]) * sr.market_hours_per_bar(tf),
                                       universe=uni, run_ref=ref),
                    source="scripts/elder_indicators_research.py",
                    evidence=(f"{ref}: raw docs/backtest_data/{os.path.basename(fn)}: PFnet {r['pfnet']}, win {r['win_pct']}%, "
                              f"n={r['n']}, avg_hold {r['avg_hold_bars']} bars; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}"),
                    notes=("Harness PFnet>1.00 (research re-implementation); main.py port + replay owed before wiring."
                           if float(r["pfnet"]) > 1.0 else "Research cell, fails PFnet>1.00 after 0.8% cost; not wired.")))
            except Exception:
                continue
    return out
