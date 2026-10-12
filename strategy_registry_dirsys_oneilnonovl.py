"""Registers (a) the Elder Directional System (Wilder DI13) 1d cells from docs/backtest_data/elder_dirsys13_results_1d.json (B-588) and
(b) the O'Neil non-overlap (strict FIFO, one position per symbol per cell) 1d tags from docs/backtest_data/oneil_nonoverlap_results_1d.json
(B-831), research-only (entry_fn=None). Nothing is wired.

Keep rule: pooled n>=30 AND (OOS n>=30 where an OOS figure exists).  Headline Metrics: for Elder the OOS (30% hold-out by entry bar)
PFnet / win % / n at cost 0.8%; pfgross and avg hold are the POOLED figures (OOS gross/hold were not measured), stated in the evidence.
For O'Neil every tag (pooled, _segis, _segoos) is its own strategy with its own numbers; none is pooled with another.
Raw files hold everything; ex-top5, trim1 and max-trade figures are in the evidence string.  Viability is derived at read time."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_REF_E = "elder dirsys13 1d (B-588; docs/backtest_data/elder_dirsys13_results_1d.json, cost 0.008, OOS headline)"
_REF_O = "oneil non-overlap 1d (B-831; docs/backtest_data/oneil_nonoverlap_results_1d.json, strict FIFO, cost 0.008)"
_D = sr.TRADING_HOURS_PER_DAY


def _load(fn):
    try:
        with open(os.path.join(_DIR, fn)) as f:
            return json.load(f)
    except Exception:
        return None


def _elder(seen):
    out = []
    d = _load("elder_dirsys13_results_1d.json")
    if not d:
        return out
    uni = f"full NSE universe file, {d.get('symbols_fetched')} symbols fetched with data, cost {d.get('cost_round_trip')} round trip"
    for r in d.get("rows", []):
        try:
            tag = r["tag"]
            if tag in seen or r.get("n", 0) < 30 or r.get("oos_n", 0) < 30 or r.get("oos_pfnet") is None:
                continue
            seen.add(tag)
            short = "__short__" in tag
            ev = (f"{_REF_E}: OOS[n={r['oos_n']} pfnet={r['oos_pfnet']} win={r['oos_win_pct']}%]; "
                  f"POOLED[n={r['n']} pfnet={r['pfnet']} pfnet_trim1={r.get('pfnet_trim1')} pfgross={r.get('pf_gross')} win={r['win_pct']}% "
                  f"avg_hold={r['avg_hold_bars']}bars avg_net={r.get('avg_net_ret_pct')}% max_trade_net={r.get('max_trade_net_ret_pct')}%]; "
                  f"exits={json.dumps(r.get('exit_reasons'), separators=(',', ':'))}")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["oos_pfnet"]), pfgross=float(r.get("pf_gross") or 0.0),
                                   win_rate_pct=float(r["oos_win_pct"]), n_trades=int(r["oos_n"]),
                                   avg_held_hrs=float(r["avg_hold_bars"]) * _D, universe=uni, run_ref=_REF_E),
                source="scripts/elder_dirsys13_research (B-588)",
                evidence=ev,
                notes=("Elder Directional System DI13 research cell. Headline pfnet/win/n are OOS; pfgross and avg hold are POOLED (OOS gross not "
                       "measured). Overlapping signals (not strict FIFO) inflate pooled n; non-overlap rerun owed before any wiring. Opposite "
                       "direction is its own tag in the same batch. Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
        except Exception:
            continue
    return out


def _oneil(seen):
    out = []
    d = _load("oneil_nonoverlap_results_1d.json")
    if not d:
        return out
    uni = f"full NSE universe file, {d.get('fetched')} symbols fetched with data, strict FIFO, cost 0.008 round trip"
    for tag, r in d.get("results", {}).items():
        try:
            if tag in seen or r.get("n", 0) < 30:
                continue
            seen.add(tag)
            seg = "IS segment" if "_segis" in tag else ("OOS segment" if "_segoos" in tag else "pooled")
            ev = (f"{_REF_O}: [{seg}] n={r['n']} pfnet={r['pfnet']} pfgross={r['pfgross']} win={r['win_pct']}% avg_hold={r['avg_hold_bars']}bars "
                  f"avg_net={r['avg_net_pct']}% pfnet_ex_top5={r.get('pfnet_ex_top5')} n_trades_gt100pct={r.get('n_trades_gt100pct')} "
                  f"raw_signals_before_fifo={r.get('raw_signal_trades_before_fifo')}; exits={json.dumps(r.get('exit_reasons'), separators=(',', ':'))}; "
                  f"top5={json.dumps(r.get('top5_trades'), separators=(',', ':'))}")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pfgross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_hrs=float(r["avg_hold_bars"]) * _D, universe=uni, run_ref=_REF_O),
                source="scripts/oneil_nonoverlap_research (B-831)",
                evidence=ev,
                notes=(f"O'Neil non-overlap 1d tag ({seg}); each of pooled/_segis/_segoos is its own strategy, never pooled together. Compare the "
                       "pooled tag with its _segoos sibling: IS-heavy edge that fades OOS is the overlap/fit risk this rerun was built to expose. "
                       "Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
        except Exception:
            continue
    return out


def build():
    seen = {x.name for x in sr.REGISTRY}
    return _elder(seen) + _oneil(seen)
