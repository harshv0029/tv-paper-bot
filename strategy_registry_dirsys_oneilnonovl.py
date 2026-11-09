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


def _pool_row(out, seen, r, uni):
    """B-1472 (2026-11-09; user 2026-11-05/06: pooled PFnet decides, OOS is recorded but never a veto): the Elder
    dirsys13 headline row above carries the OOS hold-out PFnet, so the POOLED (whole-run) figures are registered as
    their own "_pool" variant tag, every row with a pooled PFnet (no n / OOS-n filter). The OOS row is unchanged."""
    p = r["tag"].split("__")
    if len(p) < 6 or r.get("pfnet") is None or not r.get("n"):
        return
    p[1] = p[1] + "_pool"
    tag = "__".join(p)
    if tag in seen:
        return
    seen.add(tag)
    out.append(sr.StrategyDef(
        name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
        categories=(sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING,), timeframe="1d",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None,
        metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0),
                           win_rate_pct=float(r.get("win_pct") or 0.0), n_trades=int(r["n"]),
                           avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * _D,
                           avg_held_raw_unit="1d bars", universe=uni, run_ref=_REF_E.replace("OOS headline", "POOLED headline")),
        source="scripts/elder_dirsys13_research (B-588)",
        evidence=(f"{_REF_E}: POOLED[n={r['n']} pfnet={r['pfnet']} pfnet_trim1={r.get('pfnet_trim1')} win={r.get('win_pct')}%]; "
                  f"avg_net={r.get('avg_net_ret_pct')}%; OOS[n={r.get('oos_n')} pfnet={r.get('oos_pfnet')}] (recorded, not a veto)"),
        notes=("B-1472 pooled variant of the Elder dirsys13 cell (overlapping signals, not strict FIFO: pooled n is inflated). "
               "No main.py dirsys13 live path, so nothing is wired. Viability derived vs PFNET_LIVE_FLOOR.")))


def _elder(seen):
    out = []
    d = _load("elder_dirsys13_results_1d.json")
    if not d:
        return out
    uni = f"full NSE universe file, {d.get('symbols_fetched')} symbols fetched with data, cost {d.get('cost_round_trip')} round trip"
    for r in d.get("rows", []):
        try:
            _pool_row(out, seen, r, uni)
        except Exception:
            pass
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
                                   avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * _D, universe=uni, run_ref=_REF_E),
                source="scripts/elder_dirsys13_research (B-588)",
                evidence=ev,
                notes=("Elder Directional System DI13 research cell. Headline pfnet/win/n are OOS; pfgross and avg hold are POOLED (OOS gross not "
                       "measured). Overlapping signals (not strict FIFO) inflate pooled n; non-overlap rerun owed before any wiring. Opposite "
                       "direction is its own tag in the same batch. Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
        except Exception:
            continue
    return out


def _oneil(seen, fn="oneil_nonoverlap_results_1d.json", tf="1d", bar_days=1, ref_id="B-831", ref=None, min_n=30):
    ref = ref or _REF_O
    out = []
    d = _load(fn)
    if not d:
        return out
    uni = f"full NSE universe file, {d.get('fetched')} symbols fetched with data, strict FIFO, cost 0.008 round trip"
    for tag, r in d.get("results", {}).items():
        try:
            if tag in seen or r.get("n", 0) < min_n:
                continue
            seen.add(tag)
            seg = "IS segment" if "_segis" in tag else ("OOS segment" if "_segoos" in tag else "pooled")
            ev = (f"{ref}: [{seg}] n={r['n']} pfnet={r['pfnet']} pfgross={r['pfgross']} win={r['win_pct']}% avg_hold={r['avg_hold_bars']}bars "
                  f"avg_net={r['avg_net_pct']}% pfnet_ex_top5={r.get('pfnet_ex_top5')} n_trades_gt100pct={r.get('n_trades_gt100pct')} "
                  f"raw_signals_before_fifo={r.get('raw_signal_trades_before_fifo')}; exits={json.dumps(r.get('exit_reasons'), separators=(',', ':'))}; "
                  f"top5={json.dumps(r.get('top5_trades'), separators=(',', ':'))}")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pfgross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * bar_days * _D, universe=uni, run_ref=ref),
                source=f"scripts/oneil_nonoverlap_research ({ref_id})",
                evidence=ev,
                notes=(f"O'Neil non-overlap {tf} tag ({seg}); each of pooled/_segis/_segoos is its own strategy, never pooled together. Compare the "
                       "pooled tag with its _segoos sibling: IS-heavy edge that fades OOS is the overlap/fit risk this rerun was built to expose. "
                       "Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
        except Exception:
            continue
    return out


def build():
    seen = {x.name for x in sr.REGISTRY}
    return _elder(seen) + _oneil(seen) + _oneil(
        seen, "oneil_nonoverlap_results_1w.json", "1w", 5, "B-833",
        "oneil non-overlap 1w (B-833; docs/backtest_data/oneil_nonoverlap_results_1w.json, strict FIFO, cost 0.008, run 38245037321; avg_hold in weekly bars)") + _oneil(
        seen, "oneil_ext_main_nonovl_1d.json", "1d", 1, "B-1463",
        "oneil ext main.py-detector non-overlap 1d (B-1463; docs/backtest_data/oneil_ext_main_nonovl_1d.json, main.oneil_ext_signals + "
        "main.oneil_stop_price/oneil_exit_bar, strict FIFO, cost 0.008, run 41847222200)", min_n=1) + _oneil(
        seen, "oneil_ext_main_nonovl_1w.json", "1w", 5, "B-1463",
        "oneil ext main.py-detector non-overlap 1w (B-1463; docs/backtest_data/oneil_ext_main_nonovl_1w.json, main.oneil_ext_signals + "
        "main.oneil_stop_price/oneil_exit_bar, strict FIFO, cost 0.008, run 41847932950; avg_hold in weekly bars)", min_n=1) + _oneil(
        seen, "oneil_rsscreen_n200_nonovl_1d.json", "1d", 1, "B-1468",
        "oneil rsscreen main.py-detector non-overlap 1d, RS ranked inside the live SWING_WATCHLIST (B-1468; "
        "docs/backtest_data/oneil_rsscreen_n200_nonovl_1d.json, strict FIFO, cost 0.008, run 41855872144)", min_n=1) + _oneil(
        seen, "oneil_rsscreen_n200_nonovl_1w.json", "1w", 5, "B-1468",
        "oneil rsscreen main.py-detector non-overlap 1w, RS ranked inside the live SWING_WATCHLIST (B-1468; "
        "docs/backtest_data/oneil_rsscreen_n200_nonovl_1w.json, strict FIFO, cost 0.008, run 41855879111; avg_hold in weekly bars)", min_n=1)
