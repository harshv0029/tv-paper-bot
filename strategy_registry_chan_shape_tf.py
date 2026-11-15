"""Registers chan-shape-tf-dir-sweep-replay.yml run 43696407370 (B-1180): chan_shape LONG and SHORT (reciprocal-price
mirror), candle sizes 1d/4h/1h/15m/5m x ATR stop {1.5, 2.5, 4} x hold {5, 10} bars, REAL main.py functions, full universe,
0.8% cost, stop on every trade. Raw rows rebuilt from the aggregate-job log (artifact download 403):
docs/backtest_data/chan_shape_tf_dir_sweep_run_43696407370.json.
Tag immutability: 36 printed names equal older chan_shape research tags (different harness), so every row is registered as
its own tag with `_tfs` on the variant field (chan_shape__mom_mr_tfs__...). All 60 fail PFnet>1.00 (best 0.901); nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "chan_shape_tf_dir_sweep_run_43696407370.json")


def tfs_name(tag):
    p = tag.split("__")
    p[1] = p[1] + "_tfs"
    return "__".join(p)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_FN))
    except Exception:
        return out
    ref = f"{d['run']} (cost {d['cost_round_trip_pct']}%, main.py functions, full universe)"
    for r in d.get("rows", []):
        try:
            name, m = (r["tag"] if "_tfs__" in r["tag"] else tfs_name(r["tag"])), r["metrics"]
            if name in seen:
                continue
            seen.add(name)
            tf = name.split("__")[3]
            short = "__short__" in name
            bars = float(m["avg_held_bars"])
            ok = float(m["pfnet"]) > 1.0
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
                timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                   n_trades=int(m["n"]), avg_held_bars=bars, avg_held_hrs=bars * sr.market_hours_per_bar(tf),
                                   universe="NSE full universe (_load_nse_universe_from_file)", run_ref=ref),
                source="scripts/chan_shape_tf_dir_sweep_replay.py",
                evidence=(f"{ref}: printed as {r.get('printed_as', r['tag']).replace('~', '__')}; PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, "
                          f"n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                notes=("PFnet>1.00 on the main.py-function replay; owes a wiring decision." if ok
                       else "Fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
