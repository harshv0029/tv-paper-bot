"""Registers pl1d-tf-dir-sweep-replay.yml runs (B-1091): pattern-lab STARC full fade + gap runaway, LONG and SHORT, candle
sizes 4h/1h/15m/5m x ATR stop {2.5, 4, 6}, hold 20 bars, REAL main.py functions (pl1d_rule_fires / pl1d_short_rule_fires /
pl1d_long_entry_signal / pl1d exit), full universe, 0.8% cost, stop always attached. Raw rows (rebuilt from the merge-job
log; artifact download 403): docs/backtest_data/pl1d_tf_dir_sweep_run_<id>.json. Each tag is its own; tags already
registered are skipped. Viability derived at read time. Nothing is wired from this module."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "pl1d_tf_dir_sweep_run_*.json"))):
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
                short = "__short__" in tag
                bars = float(m["avg_held_bars"])
                ok = float(m["pfnet"]) > 1.0
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                    categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
                    timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                       n_trades=int(m["n"]), avg_held_bars=bars, avg_held_hrs=bars * sr.market_hours_per_bar(tf),
                                       universe="NSE full universe (_load_nse_universe_from_file)", run_ref=ref),
                    source="scripts/pl1d_tf_dir_sweep_replay.py",
                    evidence=(f"{ref}: raw docs/backtest_data/{os.path.basename(fn)}: PFnet {m['pfnet']}, gross {m['pfgross']}, "
                              f"win {m['win_pct']}%, n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                    notes=("PFnet>1.00 on the main.py-function sweep; wiring owed (B-1605: 4h live leg enters bar-0 signals only, "
                           "so a bar0_only replay comes first, as B-1603 did for island)." if ok
                           else "Fails PFnet>1.00 after 0.8% cost at this candle size; not wired.")))
            except Exception:
                continue
    return out
