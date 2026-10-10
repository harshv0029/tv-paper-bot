"""Registers every cell of the B-336 sector-rotation and B-343/B-344 MCX sweeps
(pass or fail) from the committed result JSONs. Each cell is its own tag; pfgross
was not recorded by these runs (0.0 = not recorded, never guessed)."""
import json
import os

import strategy_registry as sr

_DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
_SECTOR_REF = "sector-rotation-backtest.yml run 38068129079 (2026-10-10 IST, daily, ~1929 symbols, 11 sectors, cost 0.8%)"
_MCX_REF = "sector-rotation-backtest.yml run 38068186964 (scripts/mcx_strategy_sweep.py, 2026-10-10 IST, yfinance GC/SI/CL/NG/HG proxies, cost 0.8%)"


def _load(name):
    try:
        with open(os.path.join(_DOCS, name)) as fh:
            return json.load(fh)
    except Exception:
        return {}


def build():
    out = []
    sector = dict(_load("sector_rotation_results.json").get("results", {}))
    for _tf in ("1h", "4h", "15m", "5m"):  # B-341 intraday runs, present once their workflow has committed
        sector.update(_load(f"sector_rotation_results_{_tf}.json").get("results", {}))
    for tag, m in sector.items():
        short = "__short__" in tag
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
            timeframe=tag.split("__")[3], status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=m["pfnet"], pfgross=0.0, win_rate_pct=m["win_pct"], n_trades=m["n"],
                avg_held_hrs=m["avg_held_days"] * sr.TRADING_HOURS_PER_DAY,
                universe="full_nse_mapped_1929", run_ref=_SECTOR_REF),
            source="scripts/sector_rotation_backtest.py",
            evidence=f"PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, avg net {m['avg_net_pct']}% per trade.",
            notes="Sector rotation (B-336), registered pass or fail; research only, no live path."))
    mcx = _load("mcx_sweep_results.json")
    mcx = mcx.get("results", mcx)
    for tag, m in mcx.items():
        if not isinstance(m, dict) or "pfnet" not in m:
            continue
        tf = tag.split("__")[3]
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.FUTURES, categories=(sr.TradeCategory.FUTURES,),
            timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=m["pfnet"], pfgross=0.0, win_rate_pct=m["win_pct"], n_trades=m["n"],
                avg_held_hrs=m.get("avg_held_hrs"), universe="mcx_proxy_single_symbol", run_ref=_MCX_REF),
            source="scripts/mcx_strategy_sweep.py",
            evidence=f"PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, avg net {m['avg_net_pct']}% per trade.",
            notes="MCX commodity proxy sweep (B-343/B-344), single-symbol sample; short = mirrored 1/price series."))
    return out
