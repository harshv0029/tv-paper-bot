"""Registers brk20-min-rr-main-replay.yml run 43803665426 (B-1485): brk20_min_rr LONG 1h, the two wired cells (atr3_rr4,
atr4_rr4) x every band_cap=trail exit mode (fixed resting stop + each trailing-stop overlay), REAL main.py functions, full
universe, 0.8% cost. Rows from the aggregate-job log: docs/backtest_data/brk20_1h_trail_run_43803665426.json. Every row is
its own tag with variant `main_replay_b1485` (the plain printed names already belong to run 38185670883). Winner on both
cells: trailltp0d5r (peak-HIGH trail 0.5R) - atr3 1.373 -> 1.582, atr4 1.716 -> 2.014, shorter holds; wired via
main.SWING_1H_PEAK_LTP_TRAIL_CELLS."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "brk20_1h_trail_run_43803665426.json")


def tag_of(params):
    return f"brk20_min_rr__main_replay_b1485__long__1h__{params}__v1"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_FN))
    except Exception:
        return out
    ref = f"{d['run']} (cost {d['cost_round_trip_pct']}%, main.py functions, full universe)"
    for r in d.get("rows", []):
        try:
            name, m = tag_of(r["params"]), r["metrics"]
            if name in seen:
                continue
            seen.add(name)
            bars = float(m["avg_held_bars"])
            ok = float(m["pfnet"]) > 1.0
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,),
                timeframe="1h", status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                   n_trades=int(m["n"]), avg_held_bars=bars, avg_held_hrs=bars * sr.market_hours_per_bar("1h"),
                                   universe="NSE full universe (_load_nse_universe_from_file)", run_ref=ref),
                source="scripts/brk20_replay.py",  # band_cap=trail via scripts/swing_bandcap.py
                evidence=f"{ref}: printed as {r['printed_as']}; PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, "
                         f"n={m['n']}, hold {bars} bars",
                notes=("Exit variant of a wired brk20 1h cell; PFnet>1.00. trailltp0d5r is the live exit "
                       "(SWING_1H_PEAK_LTP_TRAIL_CELLS)." if ok else "Fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
