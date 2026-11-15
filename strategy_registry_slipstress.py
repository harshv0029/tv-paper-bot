"""Registers slippage-stress-replay run 43666079363 (2026-11-15 IST, B-422): the 7 replayable top viable tags, each at
cost 0.8/1.2/1.6% x min turnover 0/1/5 Cr (63 cells, every row pass or fail). Replay uses main.py drivers
(scripts/slippage_stress_replay.py) on the full NSE universe. 61/63 pass PFnet>1.00; the only fails are
gap_and_go exitexhaust at 1.6% cost with a turnover floor (0.93/0.95). Each cell is its own stress tag; the
(0.8%, 0 Cr) cell is the in-run control. Raw rows: docs/backtest_data/slippage_stress_run_43666079363.json.
These are robustness tags of already-registered strategies: nothing new is wired from them."""
import json
import os

import strategy_registry as sr

_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                  "slippage_stress_run_43666079363.json")


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
            hrs = float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY * (5.0 if tf == "1w" else 1.0)
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=hrs,
                    universe=uni, run_ref=ref),
                source="scripts/slippage_stress_replay.py",
                evidence=(f"{ref}: cost {r['cost_pct']}%, min turnover {r['min_turnover_cr']} Cr, PFnet {r['pfnet']}, "
                          f"gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, dropped {r['dropped']}, "
                          f"registry PFnet {r['registry_pfnet']}{' (CONTROL)' if r['control'] else ''}"),
                notes=("Stress cell holds PFnet>1.00 (robustness evidence for the base tag; not a separate entry)."
                       if ok else "Stress cell fails PFnet>1.00; base tag edge does not survive this cost/turnover.")))
        except Exception:
            continue
    return out
