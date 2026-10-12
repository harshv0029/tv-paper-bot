"""Registers the full cell set of oneil-ext-research.yml run 38207070547 (1d and 1w artifacts, 2026-10-12, cost 0.8%,
~2,166-symbol universe) from the committed raw TSVs under docs/backtest_data/ (all fields kept; the matching
*_results.json files hold the per-exit-reason breakdown).  Research-only (entry_fn=None); every tag is its own row,
pass or fail.  Tags already registered (e.g. the log-printed slice of run 38147513010) are skipped, never overwritten.
Viability is derived at read time from pfnet; none of these cells is wired live.

CAVEAT (overlapping-signal inflation): these cells re-enter on every qualifying bar with no strict-FIFO non-overlap
filter and no IS/OOS split, so n and PFnet are inflated by serially correlated trades.  Any cell >= PFNET_LIVE_FLOOR
needs a non-overlapping rerun plus an IS/OOS split and a main.py-calling replay before wiring.
avg_hold is in trading days (1d) or weeks (1w, converted at 5 trading days per week)."""
import csv
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FILES = (
    ("oneil_ext_1d_cells.tsv", "1d"),
    ("oneil_ext_1w_cells.tsv", "1w"),
)
_REF = "oneil-ext-research.yml run 38207070547 (2026-10-12 IST, cost 0.8%)"
_SRC = "scripts/oneil_ext_research.py"


def _hrs(tf, hold):
    if tf == "1w":
        return hold * 5 * sr.TRADING_HOURS_PER_DAY
    return hold * sr.TRADING_HOURS_PER_DAY


def build():
    out = []
    seen = {s.name for s in sr.REGISTRY}
    for fn, _tf in _FILES:
        try:
            rows = list(csv.DictReader(open(os.path.join(_DIR, fn)), delimiter="\t"))
        except Exception:
            continue
        for r in rows:
            tag = r["tag"]
            if tag in seen:
                continue
            try:
                tf = r["tf"]
                short = r["dir"] == "short"
                cat = sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING
                g = r.get("pfgross", "")
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(r["pfnet"]), pfgross=(0.0 if g in ("", "NA") else float(g)),
                        win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                        avg_held_hrs=_hrs(tf, float(r["avg_hold"])), universe="NSE ~2166 symbols",
                        run_ref=_REF),
                    source=_SRC,
                    evidence=(f"{_REF}: PFnet {r['pfnet']}, gross {g}, win {r['win_pct']}%, n={r['n']}, "
                              f"avg_hold {r['avg_hold']} {r.get('avg_hold_unit', '')}, avg_net {r.get('avg_net_pct', '')}%, "
                              f"max_trade {r.get('max_trade_net_pct', '')}%; exits {r.get('exit_reasons_json', '')}"),
                    notes=("O'Neil extension research cell; overlapping signals (no strict-FIFO non-overlap, no IS/OOS): "
                           "PFnet/n inflated, needs non-overlap + IS/OOS + main.py replay before wiring. "
                           "Viability derived from PFnet vs PFNET_LIVE_FLOOR at read time."),
                ))
                seen.add(tag)
            except Exception:
                continue
    return out
