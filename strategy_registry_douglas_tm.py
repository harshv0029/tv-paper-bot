"""Registers douglas-trademgmt-research run 43593152439 (2026-11-14 IST, 1h 730d, B-501 B-531..B-535 B-537 B-545 B-546
B-551..B-554 B-561 B-572 B-574 B-605): 480 trade-management entry/exit cells, every row pass or fail.
Harness = scripts/douglas_trade_mgmt_research.py (research re-implementation, NOT the real main.py functions), so a
PFnet>1 row here is corroboration only; wiring goes through the brk20_min_rr main_replay tags (B-798, B-1596).
Raw rows: docs/backtest_data/douglas_trademgmt_<tf>_run_<id>.json (1h run 43593152439; 15m/60d run 43728822855 and 5m/60d run 43730823714 added
2026-11-15 IST, every cell fails). Each tag is its own; tags already registered are skipped (1h file read first).
Viability derived at read time; nothing wired. avg_hold in bars of the tag's own tf."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_F = os.path.join(_DIR, "douglas_trademgmt_1h_run_43593152439.json")


def _files():
    rest = sorted(f for f in glob.glob(os.path.join(_DIR, "douglas_trademgmt_*_run_*.json")) if f != _F)
    return [_F] + rest


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in _files():
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        out.extend(_rows(d, seen))
    return out


def _rows(d, seen):
    out = []
    ref, uni = d["run_ref"], d["universe"]
    for r in d["rows"]:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            tf = tag.split("__")[3]
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            ok = float(r["pfnet"]) > 1.0
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                    avg_held_hrs=float(r["avg_hold_bars"]) * sr.market_hours_per_bar(tf),
                    universe=uni, run_ref=ref),
                source="scripts/douglas_trade_mgmt_research.py",
                evidence=(f"{ref}: PFnet {r['pfnet']}, gross {r['pf_gross']}, win {r['win_pct']}%, n={r['n']}, "
                          f"avg_hold {r['avg_hold_bars']} bars, MFE {r['mfe_r']}R, losers>=0.5R {r['loser_ge_half_r_pct']}%, "
                          f"losers>=1R {r['loser_ge_1r_pct']}%; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}"),
                notes=("Harness PFnet>1.00; research re-implementation, not main.py functions: corroborates "
                       "brk20_min_rr main_replay (B-1596 owes the wiring check). Not wired from this row."
                       if ok else "Research cell, fails PFnet>1.00 after 0.8% cost; not wired.")))
        except Exception:
            continue
    return out
