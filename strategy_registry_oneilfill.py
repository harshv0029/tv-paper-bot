"""Completes missing metric fields (gross PFnet, avg hold) of O'Neil registry rows from the full re-run oneil-research.yml run 38183170721
(2026-10-12 IST, 1w/1d, 0.8% cost, ~1954 symbols per timeframe).  A field is filled ONLY when the re-run reproduces the stored row exactly
(same n, PFnet within 0.011); rows the re-run does not reproduce are left untouched (different sample).  Stored values are never
overwritten; only None/0 fields are completed (CLAUDE.md: a result with missing fields is completed from the run's artifacts)."""
import dataclasses
import json
import os

import strategy_registry as sr

_D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_REF = "oneil-research.yml re-run 38183170721 (2026-10-12 IST, ~1954 symbols/timeframe, cost 0.8%)"


def apply():
    res = {}
    for tf in ("1w", "1d"):
        try:
            res.update(json.load(open(os.path.join(_D, f"oneil_rerun_{tf}_run_38183170721.json")))["results"])
        except Exception:
            pass
    for i, s in enumerate(sr.REGISTRY):
        try:
            r = res.get(s.name)
            m = s.metrics
            if not r or not m or s.source != "scripts/oneil_research.py":
                continue
            if m.n_trades != r["n"] or abs(m.pfnet - r["pfnet"]) > 0.011:
                continue
            mult = 5 * sr.TRADING_HOURS_PER_DAY if "__1w__" in s.name else sr.TRADING_HOURS_PER_DAY
            upd = {}
            if not m.pfgross and r.get("pfgross"):
                upd["pfgross"] = float(r["pfgross"])
            if not m.avg_held_hrs and r.get("avg_held_bars"):
                upd["avg_held_hrs"] = float(r["avg_held_bars"]) * mult
            if m.universe == "unconfirmed":
                upd["universe"] = "~1954 symbols with data (full re-run, exact reproduction)"
            if upd:
                upd["run_ref"] = f"{m.run_ref}; completed from {_REF}"
                sr.REGISTRY[i] = dataclasses.replace(s, metrics=dataclasses.replace(m, **upd))
        except Exception:
            continue
