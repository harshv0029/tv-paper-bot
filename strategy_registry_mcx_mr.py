"""Registers the B-1270 main-calling replay of the 8 live-wired MCX daily cells (run 38582151119, scripts/mcx_live_replay.py, which drives the
REAL main._mcx_daily_flags on COMEX proxy dailies): each cell its OWN row, the research tag with `_mr` appended to the variant (same
convention as strategy_registry_main_replay.mr_name), pass or fail. The research rows (mcx_strategy_sweep) stay untouched. Replay PFnet and n are
real; the reported table carries no gross PFnet, win % or hold, so those are None (never copied from the research row, a different sample).
Viability is derived at read time from these metrics; the real-money gate reads them via main._STRATEGY_TAG_TO_REGISTRY_NAME."""
import json
import os

import strategy_registry as sr
from strategy_registry_main_replay import mr_name

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FN = "mcx_live_replay_run_38582151119.json"
_REF = "mcx-live-replay.yml run 38582151119 (1d COMEX proxy, scripts/mcx_live_replay.py via real main._mcx_daily_flags, cost 0.8%, atrnone: premium trailing SL live)"


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
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.FUTURES, categories=(sr.TradeCategory.FUTURES,),
                timeframe="1d", status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=r.get("pfgross"), win_rate_pct=r.get("win_pct"),
                                   n_trades=int(r["n"]), avg_held_hrs=r.get("avg_held_hrs"), universe="mcx_proxy_single_symbol", run_ref=_REF),
                source="scripts/mcx_live_replay.py (main._mcx_daily_flags, main.add_strategy_signal)",
                evidence=f"{_REF}: raw docs/backtest_data/{_FN}: replay PFnet {r['pfnet']} n={r['n']} vs research row {r['registry_pfnet']} n={r['registry_n']} "
                         f"({r['tag']})",
                notes="main.py-function replay of the research cell; research row stays unchanged. Live: MCX daily engine, single-strike option with trailing SL."))
        except Exception:
            continue
    return out
