"""Registers the cells of oneil-ext-research.yml run 38147513010 and chan-ext-research.yml run 38147514850
(2026-10-11 IST, cost 0.8%) printed in their CI logs, from committed raw TSVs (partial: logs print only top-N slices;
Artifact download was blocked).  Each tag is its own row (pass or fail).  Viability is derived at read time from pfnet.
avg_hold unit (B-1031, verified from source): oneil_ext_research.py prints hold=m["avg_held_bars"] and chan_ext_research.py prints avg_hold_bars, i.e. BARS of the cell timeframe; hours = bars x (tf minutes/60 intraday, 6.25 per 1d bar, 5 x 6.25 per 1w bar). Raw bars kept in Metrics.avg_held_bars.."""
import csv
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("oneil_ext_run_38147513010.tsv", "oneil-ext-research.yml run 38147513010", "scripts/oneil_ext_research.py"),
    ("chan_ext_run_38147514850.tsv", "chan-ext-research.yml run 38147514850", "scripts/chan_ext_research.py"),
)
_TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def _hrs(tf, hold):
    if tf in _TF_MIN:
        return hold * _TF_MIN[tf] / 60.0
    if tf == "1w":
        return hold * 5 * sr.TRADING_HOURS_PER_DAY
    return hold * sr.TRADING_HOURS_PER_DAY


def build():
    out, seen = [], set()
    for fn, ref, src in _RUNS:
        try:
            rows = list(csv.DictReader(open(os.path.join(_DIR, fn)), delimiter="\t"))
        except Exception:
            continue
        for r in rows:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            try:
                tf = tag.split("__")[3] if tag.count("__") >= 3 else "1d"
                if tag.split("__")[0].startswith("oneil_pivot") and "__x__" in tag:
                    tf = tag.split("__")[3]
                short = "__short__" in tag
                intraday = tf in _TF_MIN
                cat = sr.TradeCategory.SHORT_SELL if short else (sr.TradeCategory.BUY if intraday else sr.TradeCategory.SWING)
                g = r["pfnet_gross"]
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(r["pfnet"]), pfgross=(0.0 if g in ("", "NA") else float(g)),
                        win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                        avg_held_bars=float(r["avg_hold"]), avg_held_hrs=_hrs(tf, float(r["avg_hold"])), universe=r.get("universe") or "unconfirmed",
                        run_ref=f"{ref} (2026-10-11 IST, cost 0.8%, log-printed slice)"),
                    source=src,
                    evidence=f"{ref}: PFnet {r['pfnet']}, win {r['win_pct']}%, n={r['n']}, avg_hold(raw) {r['avg_hold']}; exits {r.get('notes', '')}",
                    notes="O'Neil/Chan extension research cell, no live path; main.py replay owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR at read time.",
                ))
            except Exception:
                continue
    return out
