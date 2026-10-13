"""Registers the chan_kalman band LONG 5m cells from intraday-flatten-rerun.yml run 38424173222 (cost 0.8%): full-universe replay
calling the real main.py chan_kalman_band_long_* functions with the 15:15 IST flatten. Only the 9 cells viable under stack id 5
are registered here (ve1d0e4+z1d0 cells failed and are not wired). Research entries (entry_fn=None); pfgross was not recorded in the
hand-off so it is stored as NaN (never guessed). The live gate reads these via main._replay_verified_tags()."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = ("chan_kalman_long_main_replay_run_38424173222.json",)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in _RUNS:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        ref = f"{fn[:-5]} (cost {d.get('cost_round_trip_pct')}%, real main.py replay)"
        for r in d.get("rows", []):
            m, name = r["metrics"], r["tag"]
            if name in seen:
                continue
            seen.add(name)
            gross = m.get("pfgross")
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(sr.TradeCategory.BUY,),
                timeframe=name.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float("nan") if gross is None else float(gross),
                                   win_rate_pct=float(m["win_pct"]), n_trades=int(m["n"]),
                                   avg_held_hrs=float(m["avg_held_hours"]), universe="NSE full universe", run_ref=ref),
                source="scripts/intraday_flatten_rerun.py",
                evidence=f"{ref}: PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, hold {m['avg_held_hours']}h",
                notes="Replayed through main.chan_kalman_band_long_* via scripts/intraday_flatten_rerun.py. Wired live in the buy engine (B-960)."))
    return out
