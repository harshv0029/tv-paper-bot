"""Registers elder-patterns-research run 43668652845 (2026-11-15 IST, 1h 730d, B-600..B-603 B-571 B-608..B-622 B-624):
249 pattern / bar / trendline cells, every row pass or fail. 7 pass PFnet>1.00, all consol__tri_desc (6 long, 1 short).
Harness = scripts/elder_patterns_research.py (research re-implementation, NOT main.py functions): B-1597 owes the
main.py port + replay + wiring. Raw rows: docs/backtest_data/elder_patterns_1h_run_43668652845.json.
Tags already registered are skipped. Viability derived at read time; nothing wired. avg_hold in 1h bars."""
import json
import os

import strategy_registry as sr

_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                  "elder_patterns_1h_run_43668652845.json")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_F))
    except Exception:
        return out
    ref, uni = d["run_ref"], d["universe"]
    for r in d["rows"]:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            tf = tag.split("__")[3]
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            ok = float(r["pfnet"]) > 1.0
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                    avg_held_hrs=float(r["avg_hold_bars"]) * (1.0 if tf == "1h" else sr.TRADING_HOURS_PER_DAY),
                    universe=uni, run_ref=ref),
                source="scripts/elder_patterns_research.py",
                evidence=(f"{ref}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, "
                          f"avg_hold {r['avg_hold_bars']} bars; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}"),
                notes=("Harness PFnet>1.00 (research re-implementation, not main.py); B-1597 owes main.py port, "
                       "replay and wiring. Not wired from this row." if ok
                       else "Research cell, fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
