"""B-1480 / B-1472 b: registers elder-b3-main-replay.yml run 41966382565 (2026-11-05 IST, 1d, cost 0.8%, full NSE universe
via main._load_nse_universe_from_file()). Every row calls the REAL main.py ports (signals from main.py), FIFO non-overlap.
Tags are the replay's own `_mr` variant tags (a new tag per the naming grammar, never the research tag). All 30 rows are
registered research-only with real metrics; none clears PFNET_LIVE_FLOOR (best 0.961), so nothing is wired.
Raw data: docs/backtest_data/elder_b3_main_replay_41966382565.json (+ _table.txt)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "elder_b3_main_replay_41966382565.json")
_REF = "elder-b3-main-replay.yml run 41966382565 (2026-11-05 IST, 1d, cost 0.008, full NSE universe, main.py ports)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            undefined = r.get("pfnet") is None
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=0.0 if undefined else float(r["pfnet"]), pfgross=float(r.get("pfgross") or 0.0),
                    win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                    avg_held_hrs=float(r["avg_held_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="full NSE (main._load_nse_universe_from_file()); cost 0.008 round trip", run_ref=_REF),
                source="scripts/elder_b3_main_replay.py",
                evidence=f"{_REF}: research tag {r.get('research_tag')} (research PFnet {r.get('research_pfnet')}, n {r.get('research_n')}); "
                         f"PFnet {r['pfnet']} (gross {r.get('pfgross')}), win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_held_bars']} bars; "
                         f"exits {json.dumps({k: v.get('n') for k, v in (r.get('exit_reasons') or {}).items()}, separators=(',', ':'))}",
                notes="Elder batch-3 main.py-port replay (B-1480). Below the floor: research-only, not wired."))
        except Exception:
            continue
    return out
