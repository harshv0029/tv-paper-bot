"""Registers the B-1265 main.py-calling full-universe 1h replay of the Minervini cup 3C cheat (run 38553281449, cup-cheat-main-replay.yml):
all 9 long cells (SWING category), pass or fail, each its OWN tag (the research tag with `_mr` appended
to the variant field, same convention as strategy_registry_main_replay.mr_name). Source JSON rows are flat (n, pfnet, pfgross, win_pct,
avg_held_bars); avg hold hours = bars x 1h. Viability is derived at read time from these stored metrics (never a stored flag), so the
short rows (PFnet < floor) are gated closed automatically and the long atr4_h30 / atr6_h30 rows open the real-money gate (B-1266)."""
import json
import os

import strategy_registry as sr
from strategy_registry_main_replay import mr_name

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FN = "cup_cheat_main_replay_run_38553281449.json"
_REF = "cup-cheat-main-replay.yml run 38553281449 (1h, 730d, full NSE universe, cost ROUND_TRIP_COST_PCT, main.cup_cheat_3c_entry_signal/exit_reason, ATR stop attached)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(os.path.join(_DIR, _FN)))
    except Exception:
        return out
    for r in d.get("rows", []):
        try:
            name = mr_name(r["tag"])
            if "_mr__" not in name or name in seen:
                continue
            seen.add(name)
            long_ = r["direction"] == "long"
            bars = float(r["avg_held_bars"])
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SWING if long_ else sr.TradeCategory.SHORT_SELL,),
                timeframe="1h", status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pfgross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_hrs=bars, avg_held_bars=bars, avg_held_raw_unit="1h bars",
                                   universe="NSE full universe", run_ref=_REF),
                source="scripts/cup_cheat_main_replay.py (main.cup_cheat_3c_entry_signal / cup_cheat_3c_exit_reason)",
                evidence=f"{_REF}: raw docs/backtest_data/{_FN}: PFnet {r['pfnet']}, gross {r['pfgross']}, win {r['win_pct']}%, n={r['n']}, "
                         f"avg hold {bars} 1h bars (~{bars}h), ATR x{r['atr']}, max hold {r['hold_bars']} bars",
                notes=("Live path (B-1266): 1h leg of the swing engine (_run_long_swing_1h_pass / _cup_cheat_long_1h_try_entry), ATR stop always attached, "
                       "real mirror via _maybe_place_real_swing_entry (SL attach, unwind on failure). " if long_ else
                       "Short mirror: below PFNET_LIVE_FLOOR, gated closed, no live path. ")
                      + f"main.py-function replay of {r['tag']}; research tag stays unchanged. Only timeout exits profit; stop exits lose."))
        except Exception:
            continue
    return out
