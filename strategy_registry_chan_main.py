"""Registers intraday-flatten-rerun.yml chan_kalman_main runs 38390561217 (cost 0.8%) and 38394789725 (cost 0.3%): full-universe
replays that call the real main.py chan_kalman_band_short_* functions bar by bar with the 15:15 IST flatten. Each cell is its own tag
(`band_mr`; the 0.3% runs carry `cst0d3`). Research entries (entry_fn=None); the live gate reads these via main._replay_verified_tags().
Exit breakdowns stay in the run's merge.txt artifact."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = ("chan_kalman_main_replay_run_38390561217.json", "chan_kalman_main_replay_run_38394789725.json")


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
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(sr.TradeCategory.SHORT_SELL,),
                timeframe=name.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                   n_trades=int(m["n"]), avg_held_hrs=float(m["avg_held_hours"]),
                                   universe="NSE full universe", run_ref=ref),
                source="scripts/intraday_flatten_rerun.py",
                evidence=f"{ref}: PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, n={m['n']}, hold {m['avg_held_hours']}h",
                notes="Replayed through main.chan_kalman_band_short_* via scripts/intraday_flatten_rerun.py (chan_kalman_main). Not wired live. Cells viable at both 0.8% and 0.3% are the wiring candidates (B-914)."))
    return out
