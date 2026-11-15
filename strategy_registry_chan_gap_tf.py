"""Registers chan-gap-tf-sweep.yml runs (B-1020): chan_gap buy_on_gap long / short_on_gap short at intraday candle sizes.
Harness scripts/chan_gap_tf_sweep.py calls the REAL main.chan_gap_entry_signal / chan_gap_select_top / chan_gap_exit_reason,
full universe (main._load_nse_universe_from_file()), 0.8% cost, ATR stop on every trade, same-day flatten.
Raw rows: docs/backtest_data/chan_gap_tf_sweep_<tf>_run_<id>.json (rebuilt from the merge-job log; artifact download 403).
Each tag is its own; tags already registered are skipped. Viability derived at read time; nothing wired from here.
Hold is one session (entry at the open, stop or flatten the same day): avg_held_hrs = sessions x 6.25 market hours."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "chan_gap_tf_sweep_*_run_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        ref = f"{d['run']} ({d['interval']}, {d['period']}, cost {d['cost_round_trip_pct']}%, main.py functions)"
        for r in d.get("rows", []):
            try:
                tag, m = r["tag"], r["metrics"]
                if tag in seen:
                    continue
                seen.add(tag)
                short = "__short__" in tag
                bars = float(m.get("avg_held_bars") or 1.0)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY,
                    categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.BUY,),
                    timeframe=tag.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                       n_trades=int(m["n"]), avg_held_bars=None, avg_held_raw_unit=f"{bars} sessions (same-day hold, not tf bars)",
                                       avg_held_hrs=bars * sr.TRADING_HOURS_PER_DAY,
                                       universe="NSE full universe (_load_nse_universe_from_file), per-day top 10", run_ref=ref),
                    source="scripts/chan_gap_tf_sweep.py",
                    evidence=(f"{ref}: raw docs/backtest_data/{os.path.basename(fn)}: PFnet {m['pfnet']}, gross {m['pfgross']}, "
                              f"win {m['win_pct']}%, n={m['n']}; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                    notes=("PFnet>1.00 on the main.py-function sweep; wiring owed (show the user first)." if float(m["pfnet"]) > 1.0
                           else "Fails PFnet>1.00 after 0.8% cost at this candle size; not wired. Small n (yfinance intraday cap).")))
            except Exception:
                continue
    return out
