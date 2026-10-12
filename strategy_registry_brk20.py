"""Registers brk20-min-rr-main-replay.yml run 38185670883 (2026-10-12 IST, 15m/1h/1d, cost 0.8%, main.py brk20 functions): 72 brk20_min_rr cells, one tag each.
Raw table docs/backtest_data/brk20_run_38185670883.json.  Replay calls the real main.brk20_min_rr_entry_signal/exit_reason;
viability derived at read time; nothing wired live. be1 vs none identical in 5 of 36 groups (noted, not a bug proof)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "brk20_run_38185670883.json")
_REF = "brk20-min-rr-main-replay.yml run 38185670883 (2026-10-12 IST, 15m/1h/1d, cost 0.8%, main.py brk20 functions)"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            m = r["metrics"]
            r = dict(r, pfnet=m["pfnet"], pf_gross=m.get("pfgross"), win_pct=m["win_pct"], n=m["n"],
                     avg_hold_bars=m["avg_held_bars"], avg_net_ret_pct=m.get("avg_net_pct"), exit_reasons=m.get("exit_reasons"))
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            tf = tag.split("__")[3]
            short = "__short__" in tag
            cat = sr.TradeCategory.SHORT_SELL if short else (sr.TradeCategory.SWING if tf == "1d" else sr.TradeCategory.BUY)
            hrs = float(r["avg_hold_bars"]) * (sr.TRADING_HOURS_PER_DAY if tf == "1d" else 1.0)
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING if tf == "1d" else sr.AssetClass.EQUITY_INTRADAY,
                categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_hrs=hrs,
                    universe="NSE harness universe (full, brk20 shards)", run_ref=_REF),
                source="scripts/brk20_replay.py",
                evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r.get('pf_gross')}, win {r['win_pct']}%, n={r['n']} , avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                notes="brk20_min_rr cell; ATR stop in every cell; main.py function replay; live wiring owed (B-798). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
