"""Registers brk20-isoos run 38247769897 (cutoff 2026-09-18 IST, 730d, cost 0.8%, main.py brk20 functions) as NEW research-only tags.
Each of the 72 brk20_min_rr cells yields an in-sample (`main_replay_is`) and out-of-sample (`main_replay_oos`) tag (OOS n >= 30 only);
the existing full-period `main_replay` tags are untouched.  Raw table docs/backtest_data/brk20_isoos_run_38247769897.json.
Viability is derived at read time; nothing wired live (B-798)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "brk20_isoos_run_38247769897.json")
_REF = "brk20-isoos run 38247769897 (cutoff 2026-09-18, 730d, cost 0.8%, main.py brk20 functions)"
MIN_OOS_N = 30


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            if int(r["oos"]["n"]) < MIN_OOS_N:
                continue
            base = r["tag"]
            tf = r["interval"]
            short = r["direction"] == "short"
            cat = sr.TradeCategory.SHORT_SELL if short else (sr.TradeCategory.SWING if tf == "1d" else sr.TradeCategory.BUY)
            for side, suffix in (("is", "main_replay_is"), ("oos", "main_replay_oos")):
                m = r[side]
                tag = base.replace("__main_replay__", "__%s__" % suffix, 1)
                if tag in seen or tag == base:
                    continue
                seen.add(tag)
                hrs = float(m["avg_held_bars"]) * (sr.TRADING_HOURS_PER_DAY if tf == "1d" else 1.0)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING if tf == "1d" else sr.AssetClass.EQUITY_INTRADAY,
                    categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(
                        pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0.0), win_rate_pct=float(m["win_pct"]),
                        n_trades=int(m["n"]), avg_held_hrs=hrs,
                        universe="NSE harness universe (full, brk20 shards)", run_ref=_REF),
                    source="scripts/brk20_replay.py",
                    evidence=f"{_REF}, {side.upper()} split: PFnet {m['pfnet']}, gross {m.get('pfgross')}, win {m['win_pct']}%, n={m['n']}, avg_hold {m['avg_held_bars']} bars, avg_net {m.get('avg_net_pct')}%, avg_gross {m.get('avg_gross_pct')}%; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}; derived {json.dumps(r.get('derived'), separators=(',', ':'))}",
                    notes=f"brk20_min_rr cell {side.upper()} half (entry date {'<' if side == 'is' else '>='} 2026-09-18); research-only, entry_fn=None; live wiring needs user go-ahead (B-798). Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
        except Exception:
            continue
    return out
