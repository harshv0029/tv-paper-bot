"""Registers two research runs, every row pass or fail (none pass: best PFnet 0.871 / 0.867):
- elder-stop-offset-research.yml run 43666082279 (2026-11-15 IST, 1d 5y, B-606): 84 stop-offset / round-number tags.
- elder-batch3-research.yml run 43593142428 (2026-11-14 IST, 1h 730d, osc+struct): 270 tags.
- elder-stop-offset-research.yml run 43769949221 (2026-11-16 IST, 1h 730d, B-606): 84 tags, all fail (best 0.698).
Raw rows parsed from each run's merge-job table: docs/backtest_data/elder_stop_offset_run_43666082279.json and
docs/backtest_data/elder_batch3_1h_run_43593142428.json. Tags already registered are skipped, never renamed.
Viability derived at read time; nothing wired.  avg_hold in bars of the tag's timeframe."""
import json
import os

import strategy_registry as sr

_D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FILES = ("elder_stop_offset_run_43666082279.json", "elder_batch3_1h_run_43593142428.json",
          "elder_stop_offset_run_43769949221.json")
_HRS_PER_BAR = {"1d": sr.TRADING_HOURS_PER_DAY, "1h": 1.0}


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in _FILES:
        try:
            d = json.load(open(os.path.join(_D, fn)))
        except Exception:
            continue
        ref, uni = d["run_ref"], d["universe"]
        for r in d["rows"]:
            try:
                tag = r["tag"]
                if tag in seen:
                    continue
                seen.add(tag)
                tf = tag.split("__")[3]
                cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                        n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                        avg_held_hrs=float(r["avg_hold_bars"]) * _HRS_PER_BAR.get(tf, 1.0),
                        universe=uni, run_ref=ref),
                    source="scripts/elder_stop_offset_research.py" if fn.startswith("elder_stop") else "scripts/elder_batch3_research.py",
                    evidence=f"{ref}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
                    notes="Research cell, fails PFnet>1.00 after 0.8% cost; not wired. Viability derived from raw metrics."))
            except Exception:
                continue
    return out
