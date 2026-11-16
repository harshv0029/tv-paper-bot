"""Registers the full cell set of chan-ext-research.yml run 43777006555 (B-783 rerun, 2026-11-16 IST, cost 0.8%):
1d, 4h, 1h, 15m and 5m per-cell TSVs committed under docs/backtest_data/ (all fields kept, no top-N truncation).
Research-only (entry_fn=None); every tag is its own row, pass or fail.  Tags already registered by an earlier module
(e.g. the log-printed slice of run 38147514850) are skipped, never overwritten.  Viability is derived at read time
from pfnet; none of these cells is wired live by this module.

CAVEAT (overlapping-signal inflation): cells re-enter on every qualifying bar, no strict-FIFO non-overlap filter and
no IS/OOS split.  Any cell above PFNET_LIVE_FLOOR needs a non-overlap rerun and a main.py-calling replay before wiring."""
import csv
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_REF = "chan-ext-research.yml run 43777006555 (2026-11-16 IST, cost 0.8%)"
_SRC = "scripts/chan_ext_research.py"
_FILES = tuple((f"chan_ext_{tf}_cells_run_43777006555.tsv", _REF, _SRC) for tf in ("1d", "4h", "1h", "15m", "5m"))
_HRS_PER_UNIT = {"trading days": sr.TRADING_HOURS_PER_DAY, "weeks": 5 * sr.TRADING_HOURS_PER_DAY, "4h bars": 4.0, "1h bars": 1.0,
                 "15m bars": 0.25, "5m bars": 5 / 60}


def build():
    out = []
    seen = {s.name for s in sr.REGISTRY}
    for fn, ref, src in _FILES:
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
                intraday = tf in ("1h", "15m", "5m")
                if short:
                    cat = sr.TradeCategory.SHORT_SELL
                else:
                    cat = sr.TradeCategory.BUY if intraday else sr.TradeCategory.SWING
                g = r.get("pfgross", "")
                hold = float(r["avg_hold"])
                hrs = hold * _HRS_PER_UNIT.get(r.get("avg_hold_unit", ""), 1.0)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=(sr.AssetClass.EQUITY_INTRADAY if intraday else sr.AssetClass.EQUITY_SWING),
                    categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(r["pfnet"]), pfgross=(0.0 if g in ("", "NA") else float(g)),
                        win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                        avg_held_bars=hold, avg_held_hrs=hrs, universe="NSE full universe file (harness)",
                        run_ref=ref),
                    source=src,
                    evidence=(f"{ref}: PFnet {r['pfnet']}, gross {g}, win {r['win_pct']}%, n={r['n']}, "
                              f"avg_hold {r['avg_hold']} {r.get('avg_hold_unit', '')}, avg_net {r.get('avg_net_pct', '')}%, "
                              f"max_trade {r.get('max_trade_net_pct', '')}%; exits {r.get('exit_reasons_json', '')}"),
                    notes=("B-783 full-cell rerun research cell; overlapping signals (no strict-FIFO non-overlap, no IS/OOS): "
                           "needs non-overlap + main.py replay before wiring. Viability derived at read time."),
                ))
                seen.add(tag)
            except Exception:
                continue
    return out
