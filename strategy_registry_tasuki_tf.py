"""Registers tasuki-tf-dir-sweep-replay.yml run 43701581391 (B-1181): tasuki gap SHORT and LONG mirror, candle sizes
1d/4h/1h/15m/5m x ATR {2.5, 4, 6} x universe {etf, full}, REAL main.py functions, 0.8% cost, stop on every trade. Rows rebuilt
from the aggregate-job log (artifact 403): docs/backtest_data/tasuki_tf_dir_sweep_run_43701581391.json. 8 printed names equal
older tags, so every row carries `_tfs` (tasuki__gap_etf_tfs__...). Only etf short 1d passes (1.203, n83, already live under
its plain tags); the `_tfs` etf short 1d tags are wired after the plain ones in TASUKI_SHORT_CELLS."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "tasuki_tf_dir_sweep_run_43701581391.json")


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
                source="scripts/tasuki_tf_dir_sweep_replay.py",
                evidence=(f"{ref}: printed as {r.get('printed_as', r['tag']).replace('~', '__')}; PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, "
                          f"n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                notes=("PFnet>1.00 on the main.py-function replay; wired in TASUKI_SHORT_CELLS after the plain-named tags (same rule)." if ok
                       else "Fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
