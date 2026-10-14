"""Registers B-412 run 38169623485 (2026-10-12 IST, 1d, cost 0.8%): breakeven-after-1R (be1d0r) vs no-breakeven (benone) for
gap/minervini/ob/vp long+short, plus Minervini lab v2 replay tags not already registered.  Raw data: data/run-artifacts branch
run-38169623485/b412-all/b412_all.json (copy in docs/backtest_data/b412_run_38169623485.json).  Existing tags skipped; viability
derived at read time; nothing wired."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "b412_run_38169623485.json")
_REF = "b412-breakeven-research.yml run 38169623485 (2026-10-12 IST, 1d, cost 0.8%)"


def _m(r, uni):
    return sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r.get("pfgross") or r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                      n_trades=int(r["n"]), avg_held_bars=float(r["avg_held_bars"]), avg_held_hrs=float(r["avg_held_bars"]) * sr.TRADING_HOURS_PER_DAY, universe=uni, run_ref=_REF)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))
    except Exception:
        return out
    for x in rows:
        try:
            uni = f"{x.get('n_symbols')} symbols with data (broad NSE+ETF harness universe)"
            if "tag_be" in x:
                cat = sr.TradeCategory.SHORT_SELL if x["direction"] == "short" else sr.TradeCategory.SWING
                for tag, key in ((x["tag_baseline"], "baseline"), (x["tag_be"], "be")):
                    r = x[key]
                    if tag in seen or r.get("pfnet") is None:
                        continue
                    seen.add(tag)
                    out.append(sr.StrategyDef(
                        name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                        status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=_m(r, uni),
                        source="scripts/breakeven_research.py",
                        evidence=f"{_REF}: {key} PFnet {r['pfnet']:.3f}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_held_bars']} bars; exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}",
                        notes="B-412 breakeven-at-1R comparison; neutral overall (see STRATEGY_LEARNINGS). SL is part of every cell."))
            elif "tag_replay_v2" in x:
                tag, r = x["tag_replay_v2"], x["metrics"]
                if tag in seen or r.get("pfnet") is None:
                    continue
                seen.add(tag)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe="1d",
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None, metrics=_m(r, uni),
                    source="main.minervini_vcp_entry_signal (real) + exits ported from scripts/minervini_lab.py",
                    evidence=f"{_REF}: PFnet {r['pfnet']:.3f}, win {r['win_pct']}%, n={r['n']}, avg_hold {r['avg_held_bars']} bars",
                    notes="Minervini lab v2 replay (real entry, ported exits); main.py exit port owed before wiring."))
        except Exception:
            continue
    return out
