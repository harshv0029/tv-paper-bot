"""B-1265 (2026-11-02 IST): registers the PARTIAL main.py-calling chan_shape 1d long replay (run 38553284949,
chan-shape-main-replay.yml). Only the best cell's PFnet 0.907 and n 48019 survive in the repo (backlog row B-1265); pfgross, win %,
hold and exit reasons are None (never guessed) until artifact chan_shape-main-replay-results (id 11887209982) is transcribed into
docs/backtest_data. The tag carries the param rid38553284949 so it never collides with run 40572999957's own _mr tag for the same cell
(strategy_registry_b1396). Research entry (entry_fn=None); viability derived at read time (0.907 < floor, gate closed).
The cup 3C cheat half of B-1265 (run 38553281449) is already registered in full by strategy_registry_cup_cheat_mr."""
import json
import os

import strategy_registry as sr
from strategy_registry_main_replay import mr_name

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FN = "chan_shape_main_replay_run_38553284949_partial.json"
_REF = "chan-shape-main-replay.yml run 38553284949 (1d, full NSE, cost 0.8%, FIFO; PARTIAL: best cell only, artifact id 11887209982 owed)"


def _f(v):
    return None if v is None else float(v)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(os.path.join(_DIR, _FN)))
    except Exception:
        return out
    for r in d.get("rows", []):
        try:
            m = r["metrics"]
            name = mr_name(r["tag"])
            if "_mr__" not in name or name in seen or m.get("pfnet") is None:
                continue
            seen.add(name)
            bars = _f(m.get("avg_held_bars"))
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=_f(m.get("pfgross")), win_rate_pct=_f(m.get("win_pct")),
                                   n_trades=int(m["n"]), avg_held_hrs=None if bars is None else bars * sr.TRADING_HOURS_PER_DAY,
                                   avg_held_bars=bars, avg_held_raw_unit="1d bars" if bars is not None else "",
                                   universe="NSE full universe", run_ref=_REF),
                source="scripts/chan_shape_macddiv_main_replay.py",
                evidence=f"{_REF}: raw docs/backtest_data/{_FN}: PFnet {m['pfnet']}, gross {m.get('pfgross')}, win {m.get('win_pct')}, "
                         f"n={m['n']} (cell {r.get('source_cell')}; other 5 cells PFnet 0.73-0.86 per B-1265, per-cell values owed)",
                notes=f"PARTIAL main.py-function replay of {r.get('source_cell')} (B-1265); None fields are owed from artifact 11887209982, "
                      "not zero. Below PFNET_LIVE_FLOOR, gate closed; the later run 40572999957 re-measured this cell at 0.891 (n 48369)."))
        except Exception:
            continue
    return out
