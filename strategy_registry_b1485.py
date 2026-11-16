"""B-1485: registers the band_cap=trail main.py replays of the wired swing cells (sector-rotation-backtest.yml runs of
scripts/chan_kalman_main_replay_job.py etc.; raw JSON docs/backtest_data/<job>_<tf>_bandcap.json).  Each band_cap
mode (live = Kotak band-clamped resting stop, live_tr*/be*/lt* = trail overlays of scripts/swing_bandcap.py) is its
own tag; the off baseline is registered elsewhere and skipped.  Research rows (entry_fn=None); viability derived at
read time.  The wiring decision (trail only when it beats the fixed live stop, B-1484) is taken from beats_fixed."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_FILES = (("chan_kalman_main_replay_1d_bandcap.json",
           "sector-rotation-backtest.yml run 43781409223 (2026-11-16 IST, chan_kalman 1d band_cap=trail, cost 0.8%)"),
          ("chan_kalman_main_replay_1h_bandcap.json",
           "sector-rotation-backtest.yml run 43784674972 (2026-11-16 IST, chan_kalman 1h band_cap=trail, cost 0.8%)"))
_HRS = {"1d": sr.TRADING_HOURS_PER_DAY, "1h": 1.0, "4h": 4.0, "15m": 0.25, "5m": 5 / 60}


def build():
    out, seen = [], {s.name for s in sr.REGISTRY}
    for fn, ref in _FILES:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        for r in d.get("rows", []):
            tag, m = r.get("tag"), r.get("metrics") or {}
            if not tag or tag in seen or "pfnet" not in m:
                continue
            try:
                tf = r.get("tf", "1d")
                short = r.get("direction") == "short"
                held = float(m.get("avg_held_bars", 0.0))
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                    categories=(sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.SWING,), timeframe=tf,
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross", 0.0)),
                                       win_rate_pct=float(m.get("win_pct", 0.0)), n_trades=int(m.get("n", 0)),
                                       avg_held_bars=held, avg_held_hrs=held * _HRS.get(tf, 1.0),
                                       universe=f"NSE full universe file ({d.get('symbols_kept', '?')} kept)", run_ref=ref),
                    source="scripts/chan_kalman_main_replay_job.py",  # band_cap via scripts/swing_bandcap.py
                    evidence=(f"{ref}: band_cap {r.get('band_cap')}, PFnet {float(m['pfnet']):.3f}, n={m.get('n')}, "
                              f"avg_held {held} bars, avg_net {m.get('avg_net_pct')}%, beats_fixed={r.get('beats_fixed')}"),
                    notes=f"B-1485 band_cap replay of wired cell {r.get('wired_tag', '')}; trail wired only if it beats the fixed live stop."))
                seen.add(tag)
            except Exception:
                continue
    return out
