"""Registers B-869 index-option trigger run 38218867644 (2026-10-12 IST): index (^NSEI, ^NSEBANK, ^BSESN) trigger cells with an
option-premium proxy, 5 candle sizes. Only cells with pooled all-sample n>=30 AND OOS n>=30 (79 of 360). Headline Metrics are the OOS
(30% hold-out) numbers at the 0.8% cost model; the full cell (IS/all/OOS, 0.1% cost, per-index, exit reasons) stays in
docs/backtest_data/index_option_trigger_results_<tf>.json and a compact copy is in `evidence`. Viability derived at read time.
Research only (entry_fn=None): any future live wiring MUST use a TRAILING stop-loss on the option premium (2026-10-08 rule)
and an always-attached SL/SLM (2026-10-11 rule). Nothing is wired."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_HRS = {"5m": 5 / 60, "15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": sr.TRADING_HOURS_PER_DAY}
_REF = "index-option trigger run 38218867644 (2026-10-12 IST, cost 0.8%, OOS headline)"


def _blk(b, c="0.8"):
    x = b["net_by_cost_pct"][c]
    return (f"n={b['n']} pfnet={x['pfnet']:.3f} pfgross={b['pfnet_gross']:.3f} win_net={x['win_pct']:.1f}% "
            f"win_gross={b['win_pct_gross']:.1f}% hold={b['avg_hold_bars']:.1f}bars exits={json.dumps(b['exit_reasons'], separators=(',', ':'))}")


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "index_option_trigger_results_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        for tag, c in d.get("cells", {}).items():
            p = c.get("pooled", {})
            if tag in seen or p.get("all", {}).get("n", 0) < 30 or p.get("oos", {}).get("n", 0) < 30:
                continue
            seen.add(tag)
            o = p["oos"]
            x = o["net_by_cost_pct"]["0.8"]
            short = c["direction"] == "short"
            ev = (f"{_REF}: leg={c['option_leg']} atr_mult={c['atr_mult']} interval={d['interval']} max_hold={d['max_hold_bars']} bars; "
                  f"OOS[{_blk(o)}]; IS[{_blk(p['is'])}]; ALL[{_blk(p['all'])}]; "
                  f"OOS@0.1%cost pfnet={o['net_by_cost_pct']['0.1']['pfnet']:.3f}; "
                  f"per_index_all_pfnet0.8=" + ",".join(f"{k}:{v['net_by_cost_pct']['0.8']['pfnet']:.2f}(n{v['n']})"
                                                         for k, v in c.get("per_index", {}).items() if v.get("n")))
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.OPTIONS,
                categories=(sr.TradeCategory.OPTIONS,), timeframe=d["interval"],
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(x["pfnet"]), pfgross=float(o["pfnet_gross"]), win_rate_pct=float(x["win_pct"]),
                                   n_trades=int(o["n"]),
                                   avg_held_hrs=float(o["avg_hold_bars"]) * _HRS[d["interval"]],
                                   universe="3 indices (^NSEI, ^NSEBANK, ^BSESN), option-premium proxy", run_ref=_REF),
                source="scripts/index_option_trigger_research (run 38218867644)",
                evidence=ev,
                notes=("Index-option research cell (" + ("buy_put" if short else "buy_call") + "); research only, nothing wired. "
                       "Any future wiring requires a TRAILING SL on the option premium and an always-attached SL/SLM. "
                       "Headline = OOS at 0.8% cost; IS/all/0.1%-cost kept in evidence and the raw JSON. Viability derived vs PFNET_LIVE_FLOOR.")))
    return out
