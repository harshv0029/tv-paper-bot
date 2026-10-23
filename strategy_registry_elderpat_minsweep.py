"""Registers every tag of elder-patterns-research.yml run 38148955837 (228 tags, merge job 114501181545) and
minervini-sweep-lab run 38147956271 (8 tags, job 114495173832), 2026-10-11 IST, cost 0.8%, 1d bars, from the
committed raw TSVs in docs/backtest_data (full merge tables, nothing trimmed).  Each tag is its own row (pass or fail).
Viability is derived at read time from pfnet; nothing is wired.  avg_hold is in daily bars (1d).
Elder patterns: harness listed 10752 symbols, 9400 fetched with data.  Minervini sweep: UNI=full, ETFs excluded;
the log also printed a nifty200-restriction line from the main import (that line is the NSE_FULL_UNIVERSE reassignment,
which the lab does not read).  B-791 (2026-10-23 IST) CONFIRMED the requested universe from committed files: the lab calls
main._load_nse_universe_from_file() (docs/nse_universe.json, 2688 symbols, unchanged since 2026-10-05) minus main.ETF_SYMBOLS
(docs/etf_universe.json, 182 symbols, unchanged since 2026-10-08), i.e. 2506 symbols requested; the fetched count was not
recorded in the log.  The raw TSV is kept untouched; the confirmed universe string is applied here."""
import csv
import os

import strategy_registry as sr

_MINSWEEP_UNIVERSE = ("full NSE file universe minus ETFs: 2506 symbols requested (docs/nse_universe.json 2688 - 182 ETFs, "
                      "confirmed B-791 2026-10-23 IST; fetched count not logged), 1d, 6y, cost 0.8%")

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("elder_patterns_run_38148955837.tsv", "elder-patterns-research.yml run 38148955837", "scripts/elder_patterns_research.py"),
    ("minervini_sweep_run_38147956271.tsv", "minervini-sweep-lab run 38147956271", "scripts/minervini_sweep_lab.py"),
)


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
                parts = tag.split("__")
                tf = parts[3] if len(parts) >= 4 else "1d"
                short = "__short__" in tag
                cat = sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING
                g = r["pfnet_gross"]
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(r["pfnet"]), pfgross=(0.0 if g in ("", "NA") else float(g)),
                        win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                        avg_held_hrs=float(r["avg_hold"]) * sr.TRADING_HOURS_PER_DAY,
                        avg_held_bars=float(r["avg_hold"]), avg_held_raw_unit="1d bars",
                        universe=(_MINSWEEP_UNIVERSE if fn.startswith("minervini_sweep") else (r.get("universe") or "unconfirmed")),
                        run_ref=f"{ref} (2026-10-11 IST, cost 0.8%, full merge table)"),
                    source=src,
                    evidence=f"{ref}: PFnet {r['pfnet']} (gross {g}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_hold']} bars; exits {r.get('notes', '')}",
                    notes="Elder-pattern / Minervini ATR-trail sweep cell, no live path; main.py replay owed before wiring. Viability derived from PFnet vs PFNET_LIVE_FLOOR at read time.",
                ))
            except Exception:
                continue
    return out
