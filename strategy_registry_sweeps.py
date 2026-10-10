"""Registers every cell of the B-336 sector-rotation and B-343/B-344 MCX sweeps
(pass or fail) from the committed result JSONs. Each cell is its own tag; pfgross
was not recorded by these runs (0.0 = not recorded, never guessed)."""
import json
import os

import strategy_registry as sr

_DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
_SECTOR_REF = "sector-rotation-backtest.yml run 38068129079 (2026-10-10 IST, daily, ~1929 symbols, 11 sectors, cost 0.8%)"
_MCX_REF = "sector-rotation-backtest.yml run 38068186964 (scripts/mcx_strategy_sweep.py, 2026-10-10 IST, yfinance GC/SI/CL/NG/HG proxies, cost 0.8%)"

# cells wired into main._run_mcx_daily_scan (_MCX_DAILY_CELLS); keep in sync
_MCX_LIVE_WIRED = {
    "sma_crossover__gc__long__1d__atrnone__v1",
    "keltner_channel_breakout__si__long__1d__atrnone__v1",
    "supertrend__si__long__1d__atrnone__v1",
    "sma_crossover__ng__short__1d__atrnone__v1",
}

# sector cells wired into main._run_sector_rotation_entries
_SECTOR_LIVE_WIRED = {"sector_rotation__momentum_n200__long__1d__atr6d0_h20_l5_n1__v1"}

# pattern-lab cells wired into main._run_pattern_cell_entries (n200 results)
_PATTERN_LIVE_WIRED = {
    "gap__runaway__long__1d__atr6_h20__v1",
    "starc__fade__long__1d__atr6_h20__v1",
    "donchian__8wk_fade__long__1d__atr6_h20__v1",
    "starc__fade_etf__long__1d__atr6_h20__v1",
    "envelope__0d05_fade_etf__long__1d__atr6_h20__v1",
}


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
    for _f in ("sector_rotation_results_wide.json", "sector_rotation_fade_results_wide.json", "sector_rotation_results_n200.json", "sector_rotation_results_wide_n200.json", "sector_rotation_fade_results_n200.json", "sector_rotation_fade_results_wide_n200.json"):  # B-348 wide stops
        sector.update(_load(_f).get("results", {}))
    for _tf in ("1d", "1h", "4h", "15m", "5m"):  # B-341 fade variant files
        sector.update(_load(f"sector_rotation_fade_results{'' if _tf == '1d' else '_' + _tf}.json").get("results", {}))
    for tag, m in sector.items():
        short = "__short__" in tag
        status = (sr.StrategyStatus.LIVE if tag in _SECTOR_LIVE_WIRED else
                  sr.StrategyStatus.VALIDATED if (m["pfnet"] and m["pfnet"] > 1 and m["n"] >= 300) else
                  sr.StrategyStatus.RESEARCH)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
            categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
            timeframe=tag.split("__")[3], status=status, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=m["pfnet"], pfgross=0.0, win_rate_pct=m["win_pct"], n_trades=m["n"],
                avg_held_hrs=m["avg_held_days"] * sr.TRADING_HOURS_PER_DAY,
                universe="full_nse_mapped_1929", run_ref=_SECTOR_REF),
            source="scripts/sector_rotation_backtest.py",
            evidence=f"PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, avg net {m['avg_net_pct']}% per trade.",
            notes="Sector rotation (B-336), registered pass or fail; research only, no live path."))
    # pattern lab (B-81..B-206 batch): each tag is its own strategy, registered pass or fail
    for _tf, _fn in (("1d", "pattern_lab_results.json"), ("1h", "pattern_lab_results_1h.json"),
                     ("15m", "pattern_lab_results_15m.json"), ("5m", "pattern_lab_results_5m.json"),
                     ("1d", "pattern_lab_results_n200.json"), ("1d", "pattern_lab_results_etf.json"),
                     ("1h", "pattern_lab_results_1h_n200.json"), ("15m", "pattern_lab_results_15m_n200.json"),
                     ("1d", "minervini_lab_results.json"), ("1d", "minervini_lab_results_full.json"),
                     ("1d", "breadth_lab_results.json"), ("1d", "combo_lab_results.json")):
        for tag, m in _load(_fn).get("results", {}).items():
            # the n200 (live swing universe) file owns the plain tag; other universes get a variant suffix so no
            # two universes ever share a name (immutability / never pool)
            _suffix = "" if ("n200" in _fn or _fn in ("minervini_lab_results.json", "breadth_lab_results.json", "combo_lab_results.json")) else (
                "_etf" if _fn.endswith("etf.json") else "_full")
            if _suffix:
                _p = tag.split("__")
                _p[1] = _p[1] + _suffix
                tag = "__".join(_p)
            short = "__short__" in tag
            hrs = m["avg_held_bars"] * m["bar_hours"]
            # conservative: registered PFnet is the one after dropping the best 1% of trades (outlier guard)
            _pf = m["pfnet"] if m.get("pfnet_trim1") is None else (min(m["pfnet"], m["pfnet_trim1"]) if m["pfnet"] else m["pfnet"])
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,),
                timeframe=_tf, status=(sr.StrategyStatus.LIVE if (tag in _PATTERN_LIVE_WIRED and (_fn.endswith("n200.json") or _fn.endswith("etf.json"))) else sr.StrategyStatus.VALIDATED if (_pf and _pf > 1 and m["n"] >= 300) else sr.StrategyStatus.RESEARCH),
                entry_fn=None,
                metrics=sr.Metrics(pfnet=_pf, pfgross=0.0, win_rate_pct=m["win_pct"], n_trades=m["n"], avg_held_hrs=hrs,
                                   universe="n200_swing_watchlist" if _fn.startswith("combo") else "nifty_index_breadth" if _fn.startswith("breadth") else "etf_universe" if _fn.endswith("etf.json") else "n200_swing_watchlist" if ("n200" in _fn or _fn == "minervini_lab_results.json") else "full_nse",
                                   run_ref="pattern-lab (scripts/pattern_lab.py via sector-rotation-backtest.yml), 2026-10-10 IST, cost 0.8%"),
                source=("scripts/minervini_lab.py" if _fn.startswith("minervini") else "scripts/breadth_lab.py" if _fn.startswith("breadth") else "scripts/combo_lab.py" if _fn.startswith("combo") else "scripts/pattern_lab.py"),
                evidence=f"PFnet {_pf} (raw {m['pfnet']}), win {m['win_pct']}%, n={m['n']}, avg net {m['avg_net_pct']}% per trade.",
                notes="Pattern lab rule, registered pass or fail; research only unless wired."))
    mcx = _load("mcx_sweep_results.json")
    mcx = mcx.get("results", mcx)
    for tag, m in mcx.items():
        if not isinstance(m, dict) or "pfnet" not in m:
            continue
        tf = tag.split("__")[3]
        # 2026-10-10 user: only PFnet>1 cells are backtested+viable and live wired.
        if tag in _MCX_LIVE_WIRED:
            status = sr.StrategyStatus.LIVE
        elif m["pfnet"] and m["pfnet"] > 1 and m["n"] >= 30:
            status = sr.StrategyStatus.VALIDATED
        else:
            status = sr.StrategyStatus.RESEARCH
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.FUTURES, categories=(sr.TradeCategory.FUTURES,),
            timeframe=tf, status=status, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=m["pfnet"], pfgross=0.0, win_rate_pct=m["win_pct"], n_trades=m["n"],
                avg_held_hrs=m.get("avg_held_hrs"), universe="mcx_proxy_single_symbol", run_ref=_MCX_REF),
            source="scripts/mcx_strategy_sweep.py",
            evidence=f"PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, avg net {m['avg_net_pct']}% per trade.",
            notes="MCX commodity proxy sweep (B-343/B-344), single-symbol sample; short = mirrored 1/price series."))
    return out
