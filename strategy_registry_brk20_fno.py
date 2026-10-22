"""B-1339: registers brk20-min-rr-main-replay.yml runs with universe=fno (NSE stock-futures underlyings only,
nse_fo_chain.STOCK_FO_UNDERLYINGS) and a futures cost override. One tag per cell (variant main_replay_fno, param costX).
Futures P&L is APPROXIMATED as point-for-point cash tracking (no basis, no roll gap); the cost param carries the roll
and slippage estimate. Raw tables docs/backtest_data/brk20_fno_run_*.json. n=0 cells are registered with zeros (a
result, not a gap). Viability derived at read time; nothing wired live (one lot >> account capital, see B-1339)."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "brk20_fno_run_*.json"))):
        run_id = os.path.basename(fn)[len("brk20_fno_run_"):-len(".json")]
        try:
            doc = json.load(open(fn))
        except Exception:
            continue
        ref = (f"brk20-min-rr-main-replay.yml run {run_id} (universe=fno, cost {doc.get('cost_round_trip_pct')}%, "
               f"period {doc.get('period')}, main.py brk20 functions)")
        for r in doc.get("rows", []):
            try:
                tag, m = r["tag"], r["metrics"]
                if tag in seen:
                    continue
                seen.add(tag)
                tf = tag.split("__")[3]
                n = int(m.get("n") or 0)
                hold = float(m.get("avg_held_bars") or 0.0)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.FUTURES, categories=(sr.TradeCategory.FUTURES,),
                    timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(m.get("pfnet") or 0.0), pfgross=float(m.get("pfgross") or 0.0),
                        win_rate_pct=float(m.get("win_pct") or 0.0), n_trades=n, avg_held_bars=hold,
                        avg_held_hrs=hold * sr.market_hours_per_bar(tf),
                        universe=f"NSE stock-futures underlyings ({r.get('n_symbols')} loaded)", run_ref=ref),
                    source="scripts/brk20_replay.py",
                    evidence=(f"{ref}: PFnet {m.get('pfnet')}, gross {m.get('pfgross')}, win {m.get('win_pct')}%, n={n}, "
                              f"avg_hold {hold} bars, avg_net {m.get('avg_net_pct')}%; exits "
                              f"{json.dumps(m.get('exit_reasons'), separators=(',', ':'))}"),
                    notes="brk20_min_rr futures-route cell (B-1339); cash-price approximation; ATR stop every trade; "
                          "not wired (capital). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
            except Exception:
                continue
    return out
