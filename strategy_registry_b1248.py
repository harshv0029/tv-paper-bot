"""B-1248: registers the sector-rotation sweep cells of run 38520502338 (docs/backtest_data/sector_sweep_full_run_38520502338_*.json) that no earlier
loader registered (the new atr4d0/atr6d0 stop grid, long and short fade).  Each tag is its OWN row, pass or fail, research-only (entry_fn=None).
Headline metrics use the gap_aware stop-fill model (a stop that gaps through fills at the open, the realistic one); the 'stop' (fills at the stop
price) and 'close' fill models stay in the evidence in full and in the raw JSON.  Zero-trade cells are kept with zeros (not evidence).
Viability is derived at read time from PFnet vs PFNET_LIVE_FLOOR; wiring needs a live path that attaches the ATR stop (not built)."""
import glob
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_HRS = {"1h": 1.0, "4h": 4.0, "1d": sr.TRADING_HOURS_PER_DAY}


def _fill(b):
    return (f"n={b['n']} pfnet={b['pfnet']} pfgross={b['pfgross']} win={b['win_pct']}% hold={b['avg_held_bars']}bars "
            f"avg_net={b['avg_net_pct']}% exits={json.dumps(b['exit_reasons'], separators=(',', ':'))}")


def build():
    seen = {x.name for x in sr.REGISTRY}
    out = []
    for fn in sorted(glob.glob(os.path.join(_DIR, "sector_sweep_full_run_38520502338_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        ref = f"sector-rotation-sweep rerun run 38520502338 ({os.path.basename(fn)}, cost 0.8%, next_open entries)"
        tf = d.get("tf", "4h")
        for tag, c in d.get("cells", {}).items():
            if tag in seen:
                continue
            seen.add(tag)
            f = c["by_stop_fill"]
            g = f["gap_aware"]
            short = "__short__" in tag
            pf = g.get("pfnet")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(pf) if pf is not None else 0.0, pfgross=float(g.get("pfgross") or 0.0),
                                   win_rate_pct=float(g["win_pct"]), n_trades=int(g["n"]), avg_held_bars=float(g["avg_held_bars"]),
                                   avg_held_hrs=float(g["avg_held_bars"]) * _HRS.get(tf, 1.0), avg_held_raw_unit=f"{tf} bars",
                                   universe=f"full NSE universe file ({d.get('universe_size')} symbols), sector-rotation picks from main.sector_rotation_fade_short_picks",
                                   run_ref=ref),
                source="scripts/sector_rotation_backtest.py (sector sweep, run 38520502338)",
                evidence=(f"{ref}: n_signals={c.get('n_signals')}; GAP_AWARE[{_fill(g)}]; STOP[{_fill(f['stop'])}]; CLOSE[{_fill(f['close'])}]"
                          + ("; zero trades: pfnet stored 0.0 is a placeholder, not a measurement" if not g["n"] else "")),
                notes=("Sector-rotation sweep cell (B-1248), registered pass or fail with the gap_aware headline; the other two stop-fill models are in evidence. "
                       "Nothing wired: a short-fade or long cell needs a live path that always attaches the ATR stop.")))
    return out
