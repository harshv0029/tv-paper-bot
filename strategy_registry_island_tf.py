"""Registers island-tf-dir-sweep-replay.yml run 43692422951 (B-1090, replay half of B-891): island reversal LONG and SHORT,
candle sizes 1d/4h/1h/15m/5m x ATR stop {1.5, 2.5, 4} x filters {none, px20, turn1cr, gap05}, REAL main.py functions
(island_swing_entry_signal / island_short_entry_signal, brk20_stop_price, brk20_min_rr_exit_reason), full universe,
0.8% cost, stop always attached. Raw rows (rebuilt from the aggregate-job log; artifact download 403):
docs/backtest_data/island_tf_dir_sweep_run_43692422951.json.
Tag immutability: the sweep prints names identical to the island-validation research tags (run 38221645245, a different
harness and exit), so each row is registered as its own tag with `_tfs` on the variant field
(reversal__island_gap05_tfs__short__1d__...); the research tags stay unchanged. Viability derived at read time.
Nothing is wired from this module: the live island long path reads its own tags; a short wiring is shown to the user first."""
import glob
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "island_tf_dir_sweep_run_43692422951.json")
# B-1603: later runs of the same harness (e.g. bar0_only=1 run 43709215753, `_b0` tags) are registered from the same dir.
_GLOB = os.path.join(os.path.dirname(_FN), "island_tf_dir_sweep_run_*.json")


def tfs_name(tag):
    p = tag.split("__")
    p[1] = p[1] + "_tfs"
    return "__".join(p)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in [_FN] + sorted(f for f in glob.glob(_GLOB) if os.path.abspath(f) != os.path.abspath(_FN)):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        out.extend(_rows(d, seen))
    return out


def _rows(d, seen):
    out = []
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
                source="scripts/island_tf_dir_sweep_replay.py",
                evidence=(f"{ref}: printed as {r.get('printed_as', r['tag']).replace('~', '__')}; PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, "
                          f"n={m['n']}, hold {bars} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                notes=(("PFnet>1.00 on the main.py-function replay. " +
                        ("Short: island_short_entry_signal is ported but NOT wired (B-891); wiring is shown to the user first."
                         if short else ("B-1603 bar-0 subset of the wired 4h _tfs long cell (the only signals the live 13:15 leg can "
                                        "enter): confirms that cell; the live tag stays the _tfs name." if "_b0__" in name else
                                        "Long: the live island path wires the 1d atr1d5 cells; other ATR/tf cells owe a wiring decision.")))
                       if ok else "Fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
