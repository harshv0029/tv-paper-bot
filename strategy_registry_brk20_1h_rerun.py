"""Registers brk20-min-rr-main-replay.yml run 43696686802 (B-1596): brk20_min_rr LONG 1h re-run, ATR {2, 3} x min R:R {2.5,
3, 4} x breakeven {none, 1R}, REAL main.py functions, full universe, 0.8% cost. Rows rebuilt from the aggregate-job log
(artifact 403): docs/backtest_data/brk20_1h_rerun_run_43696686802.json. The printed names equal the run-38185670883 tags, so
each row is its own tag with `_b1596` on the variant field. Passing: atr3_rr4 1.379 and its be1 twin 1.382; atr3_rr4 is wired
under its original name in BRK20_1H_LONG_CELLS."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "brk20_1h_rerun_run_43696686802.json")


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
            name, m = (r["tag"] if "_b1596__" in r["tag"] else tfs_name(r["tag"])), r["metrics"]
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
                source="scripts/brk20_replay.py",
                evidence=(f"{ref}: printed as {r.get('printed_as', r['tag']).replace('~', '__')}; PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, "
                          f"n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                notes=("PFnet>1.00 on the re-run; the original-named tag is the wired one (BRK20_1H_LONG_CELLS) or its be1 twin (shares the entry)." if ok
                       else "Fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
