"""Registers oneil-replay.yml run 38517583883 (14 Oct 2026, 1w bars, cost 0.8%, calls the real main.py oneil_* functions;
docs/backtest_data/oneil_main_replay_run_38517583883.json kept in full). Each tag is its own registry row, pass or fail, with every
measured field (PFnet net/gross, win %, n, avg hold in 1w bars, ex-top5 PFnet, top-5 share, symbols traded, exit-reason breakdown).
Viability is derived at read time (PFNET_LIVE_FLOOR); a live path exists only for tags main._STRATEGY_TAG_TO_REGISTRY_NAME maps
(main.ONEIL_SWING_CELLS). Avg-down cells are research controls only (engine invariant: never average down)."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "oneil_main_replay_run_38517583883.json")
_REF = "oneil-replay.yml run 38517583883 (14 Oct 2026, 1w, cost 0.8%, main.py oneil_* functions, 2703 listed / 1962 loaded)"
_HRS_PER_1W_BAR = 5 * sr.TRADING_HOURS_PER_DAY


def build():
    out = []
    try:
        d = json.load(open(_FN))
    except Exception:
        return out
    for r in d.get("rows", []):
        try:
            m, tag = r["metrics"], r["tag"]
            bars = m.get("avg_held_bars")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING,),
                timeframe="1w", status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                   n_trades=int(m["n"]), avg_held_hrs=None if bars is None else float(bars) * _HRS_PER_1W_BAR,
                                   universe=m.get("universe") or "NSE full universe", run_ref=_REF,
                                   avg_held_bars=None if bars is None else float(bars), avg_held_raw_unit="1w bars"),
                source="main.py oneil_entry_signal / oneil_signal_at / oneil_stop_price / oneil_exit_reason (live swing wiring: oneil_swing_entry_signal / oneil_swing_exit_reason)",
                evidence=f"{_REF}: PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, n={m['n']}, avg_hold {bars} 1w bars, "
                         f"ex-top5 PFnet {m.get('pfnet_ex_top5')}, top5 share {m.get('top5_share')}, syms {m.get('syms_traded')}, "
                         f"exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}",
                notes="B-1243 main.py replay of the research v1 tag (v2 = main.py-called). 339 research-vs-replay n crosscheck diffs unresolved; "
                      "universe = currently listed symbols (survivorship). Hold 11-26 weeks. Viability derived at read time; user rule 2026-10-14: PFnet floor only."))
        except Exception:
            continue
    return out
