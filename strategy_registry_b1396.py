"""B-1396 (2026-10-28 IST): registers every row of the main.py-calling replays that closed the replay-owed tags, each as its own
`_mr` tag (strategy_registry_main_replay.mr_name convention); the research tags stay registered unchanged, never overwritten.
Rows keep metrics nested (rows[].metrics) or flat (macddiv file). Research entries (entry_fn=None); viability is still derived at
read time (main._replay_verified_tags / REPLAY_FAILED_TAGS read the same JSONs). All raw fields kept in the evidence string."""
import json
import os

import strategy_registry as sr
from strategy_registry_main_replay import mr_name

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("macddiv_main_replay_run_38550669732.json", "macddiv-main-replay.yml run 38550669732 (1h, full NSE, cost 0.8%, FIFO)",
     "scripts/chan_shape_macddiv_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SWING),
    ("chan_shape_main_replay_run_40572999957.json", "chan-shape-main-replay.yml run 40572999957 (1d, full NSE, cost 0.8%, FIFO)",
     "scripts/chan_shape_macddiv_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SWING),
    ("tasuki_swingminrr_short_main_replay_run_40575438117.json",
     "tasuki-swingminrr-short-main-replay.yml run 40575438117 (tasuki 1d ETF_SYMBOLS, swingminrr 1h full NSE, cost 0.8%)",
     "scripts/tasuki_swingminrr_short_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SHORT_SELL),
    ("month_effect_main_replay_run_40580498404.json",
     "month-effect-main-replay.yml run 40580498404 (15m: one Sept-1 session; 1d: 5y; full NSE, cost 0.8%)",
     "scripts/month_effect_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SHORT_SELL),
)
_HOURS_PER_BAR = {"15m": 0.25, "1h": 1.0}


def _tf(tag: str) -> str:
    parts = tag.split("__")
    return parts[3] if len(parts) > 3 else "1d"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, ref, src, ac, cat in _RUNS:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        for r in d.get("rows", []):
            try:
                m = r["metrics"] if isinstance(r.get("metrics"), dict) else r
                name = mr_name(r["tag"])
                if "_mr__" not in name or name in seen or m.get("pfnet") is None:
                    continue
                seen.add(name)
                tf = _tf(r["tag"])
                bars = m.get("avg_held_bars")
                hrs = m.get("avg_held_hours")
                if bars is not None and tf in _HOURS_PER_BAR:
                    hrs = float(bars) * _HOURS_PER_BAR[tf]  # market hours from the row's own bar count
                elif bars is not None and tf == "1d":
                    hrs = float(bars) * sr.TRADING_HOURS_PER_DAY
                out.append(sr.StrategyDef(
                    name=name, asset_class=ac, categories=(cat,), timeframe=tf, status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0), win_rate_pct=float(m.get("win_pct") or 0),
                                       n_trades=int(m["n"]), avg_held_hrs=None if hrs is None else float(hrs),
                                       avg_held_bars=None if bars is None else float(bars),
                                       avg_held_raw_unit=f"{tf} bars" if bars is not None else "",
                                       universe="ETF_SYMBOLS" if r["tag"].startswith("tasuki__") else "NSE full universe", run_ref=ref),
                    source=src,
                    evidence=f"{ref}: raw docs/backtest_data/{fn}: PFnet {m['pfnet']}, gross {m.get('pfgross')}, win {m.get('win_pct')}%, n={m['n']}, "
                             f"hold {hrs}h, exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}",
                    notes=f"B-1396 main.py-function replay of {r['tag']}; the research tag stays registered unchanged."
                          + (" 15m: all trades on ONE Sept-1 session (single market day)." if r["tag"].startswith("month__") and tf == "15m" else "")))
            except Exception:
                continue
    return out
