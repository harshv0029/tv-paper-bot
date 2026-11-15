"""Registers gatetarget-short-sweep-replay.yml runs (B-1010): swingminrr brk20 gatetarget SHORT cell at 4h / 15m / 5m x
ATR {2,3,4,6} (hold 30 bars, rr 4), real main.py functions, full universe (_load_nse_universe_from_file), 0.8% cost.
Raw rows: docs/backtest_data/gatetarget_short_tf_sweep_run_<id>.json (rebuilt from the merge-job log; artifact 403).
Each tag is its own (the 1h cell keeps its existing tag); tags already registered are skipped. Nothing is wired from
here; viability is derived at read time."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "gatetarget_short_tf_sweep_run_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        ref = f"{d['run']} (cost {d['cost_round_trip_pct']}%, main.py functions, full universe)"
        for r in d.get("rows", []):
            try:
                tag, m = r["tag"], r["metrics"]
                if tag in seen:
                    continue
                seen.add(tag)
                tf = tag.split("__")[3]
                bars = float(m["avg_held_bars"])
                ok = float(m["pfnet"]) > 1.0
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SHORT_SELL,),
                    timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                       n_trades=int(m["n"]), avg_held_bars=bars, avg_held_hrs=bars * sr.market_hours_per_bar(tf),
                                       universe="NSE full universe (_load_nse_universe_from_file)", run_ref=ref),
                    source="scripts/gatetarget_short_sweep_replay.py",
                    evidence=(f"{ref}: raw docs/backtest_data/{os.path.basename(fn)}: PFnet {m['pfnet']}, gross {m['pfgross']}, "
                              f"win {m['win_pct']}%, n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                    notes=("PFnet>1.00 on the main.py-function sweep; wiring owed (show the user first)." if ok
                           else "Fails PFnet>1.00 after 0.8% cost at this candle size; not wired.")))
            except Exception:
                continue
    return out
