"""Registers elder-trend-context-research run 43689022041 (2026-11-15 IST, 4h 730d, after the B-1598 fetch fix): 210 regime / MA / oscillator
cells, every row pass or fail. 0 pass PFnet>1.00 (best 0.923, osc__gap_timestop long atr3_nb2). The 1d run
38209280422 also had 0 passes (best 0.984). Raw rows: docs/backtest_data/elder_trend_context_4h_run_43689022041.json.
Tags already registered are skipped. Viability derived at read time; nothing wired. avg_hold in 4h bars."""
import json
import os

import strategy_registry as sr

_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                  "elder_trend_context_4h_run_43689022041.json")


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
                    avg_held_hrs=float(r["avg_hold_bars"]) * sr.market_hours_per_bar(tf),
                    universe=uni, run_ref=ref),
                source="scripts/elder_trend_context_research.py",
                evidence=(f"{ref}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, "
                          f"avg_hold {r['avg_hold_bars']} bars; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}"),
                notes=("Harness PFnet>1.00; needs a main.py replay before wiring." if ok
                       else "Research cell, fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
