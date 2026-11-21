"""Registers the swing minimum reward:risk 1h/730d tags (B-842, run 38249384880) from docs/backtest_data/swingminrr_1h_730d_run_38249384880.json,
research-only (entry_fn=None). Nothing is wired. Keep rule: n>=30. Every tag is its own strategy (gate / gatetarget / target / base
variants, long and short, never pooled). Raw file holds every field (including the n<30 rows); pfnet_ex_top5, top-5 trades, win sums
and exit reasons are in the evidence string. Viability is derived at read time."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_REF = "swing min-RR 1h/730d (B-842, run 38249384880; docs/backtest_data/swingminrr_1h_730d_run_38249384880.json, cost 0.008)"
_H = 1.0  # one 1h bar = 1 market hour


_FILES = (("swingminrr_1h_730d_run_38249384880.json", "1h", 1.0, _REF),
          ("swingminrr_4h_730d_run_44923936618.json", "4h", 4.0,
           "swing min-RR 4h/730d (B-842/B-1598, run 44923936618, 2026-11-21 IST; 1h resampled per NSE session; "
           "docs/backtest_data/swingminrr_4h_730d_run_44923936618.json, cost 0.008)"))


def build():
    out = []
    seen = {x.name for x in sr.REGISTRY}
    for fn, tf, hrs, ref in _FILES:
        out.extend(_build_one(fn, tf, hrs, ref, seen))
    return out


def _build_one(fn, tf, hrs, ref, seen):
    out = []
    try:
        with open(os.path.join(_DIR, fn)) as f:
            d = json.load(f)
    except Exception:
        return out
    uni = (f"full NSE universe file, {d.get('symbols_fetched')} of {d.get('universe_size')} symbols fetched with data, "
           f"cost {d.get('cost_round_trip')} round trip, max hold {d.get('max_hold_bars')} bars")
    for r in d.get("rows", []):
        try:
            tag = r["tag"]
            if tag in seen or r.get("n", 0) < 30:
                continue
            seen.add(tag)
            short = "__short__" in tag
            ev = (f"{ref}: n={r['n']} pfnet={r['pfnet']} pfgross={r['pf_gross']} pfnet_ex_top5={r.get('pfnet_ex_top5')} "
                  f"win={r['win_pct']}% avg_hold={r['avg_hold_bars']}bars avg_net={r.get('avg_net_ret_pct')}% "
                  f"win_sum={r.get('win_sum')} loss_sum={r.get('loss_sum')} glitch_dropped={r.get('glitch_dropped')}; "
                  f"exits={json.dumps(r.get('exit_reasons'), separators=(',', ':'))}; "
                  f"top5={json.dumps(r.get('top5'), separators=(',', ':'))}")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r["pf_gross"]), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * hrs, universe=uni, run_ref=ref),
                source="scripts/swing_min_rr_research (B-842)",
                evidence=ev,
                notes=("Swing entry with ATR stop and minimum reward:risk target/gate (variants gate, gatetarget, target, base), " + tf + ", 730d. Pooled only: NO IS/OOS split yet, so OOS decay is unknown and live wiring needs it first. Check "
                       "pfnet_ex_top5 in the evidence before reading the headline PFnet: thin-n cells are outlier-driven. No live path "
                       "exists for these variants; research only. Viability derived vs PFNET_LIVE_FLOOR; nothing wired.")))
        except Exception:
            continue
    return out
