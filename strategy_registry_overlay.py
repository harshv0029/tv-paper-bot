"""Registers portfolio-overlay-research.yml run 38176399634 (2026-10-12 IST, 1d, cost 0.8%, 2688 listed / 2351 fetched): 744 cells of the
brk20 base entry sliced by year/month/price bucket/turnover quartile/index regime/walk-forward/risk-per-trade/position-cap.  Raw table
docs/backtest_data/portfolio_overlay_run_38176399634.json keeps CI95, autocorrelation, runs-z, cost sensitivity.  Slice cells are
diagnostics of one base entry, registered as their own tags per the no-pooling rule; viability derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "portfolio_overlay_run_38176399634.json")
_REF = "portfolio-overlay-research.yml run 38176399634 (2026-10-12 IST, 1d, cost 0.8%, 2688 listed / 2351 fetched)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen or r.get("pfnet") is None:
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="2351 fetched of 2688 listed (NSE harness universe)", run_ref=_REF),
                source="scripts/portfolio_overlay_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (CI95 {r.get('pfnet_ci95_lo')}-{r.get('pfnet_ci95_hi')}), gross {r.get('pf_gross')}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold_bars']} bars, expectancy {r.get('expectancy_pct')}%, W/L {r.get('win_loss_ratio')}, ac1 {r.get('ac1')}, PFnet at cost 0.4/0.8/1.2%: {r.get('pfnet_at_cost_0.4pct')}/{r.get('pfnet_at_cost_0.8pct')}/{r.get('pfnet_at_cost_1.2pct')}; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="Portfolio-overlay slice of brk20 entry (diagnostic); main.py port + replay owed before wiring; ATR stop in every cell. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
