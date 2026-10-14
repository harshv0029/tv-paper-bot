"""Registers full-universe replays that IMPORT and CALL the real main.py functions (B-881): island run 38309068649
(docs/backtest_data/island_main_replay_run_38309068649.json). Each result is its own tag: the original tag with `_mr` appended to the
variant field (the research tag stays registered unchanged). 1d, 5y, cost 0.8%, ATR 1.5 stop attached as live, fill at the signal close.
Research entries (entry_fn=None); main._replay_verified_tags() re-opens the real-money gate for the ORIGINAL tag only when this replay
clears PFNET_LIVE_FLOOR with n>=30. Zero-trade rows (island_gap05) are kept with zeros."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("island_main_replay_run_38336515135.json", "island-main-replay.yml run 38336515135 (1d, 5y, cost 0.8%, main.py functions, gap05 fix B-887)", "scripts/island_main_replay.py"),
    ("island_main_replay_run_38309068649.json", "island-main-replay.yml run 38309068649 (1d, 5y, cost 0.8%, main.py functions)", "scripts/island_main_replay.py"),
    ("swing_short_main_replay_run_38318986997.json", "swing-short-main-replay.yml run 38318986997 (1d, 5y, cost 0.8%, main.py functions, fill at signal close)", "scripts/swing_short_main_replay.py"),
)


def mr_name(tag: str) -> str:
    return tag.replace("__long__", "_mr__long__", 1).replace("__short__", "_mr__short__", 1)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, ref, src in _RUNS:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        for r in d.get("rows", []):
            try:
                m = r["metrics"]
                name = mr_name(r["tag"])
                # B-1030: swing_short_main_replay wrote avg_held_hours as bars x 24.0 (calendar hours) while every other registry
                # entry (and island_main_replay) uses market hours = bars x TRADING_HOURS_PER_DAY. Normalize from the raw bar count
                # (kept in the JSON and in Metrics.avg_held_bars); the run's raw hours field stays untouched in the JSON and evidence.
                bars = m.get("avg_held_bars")
                raw_h = m.get("avg_held_hours")
                if bars is not None:
                    hrs, raw_unit = float(bars) * sr.TRADING_HOURS_PER_DAY, "1d bars"
                else:
                    hrs, raw_unit = float(raw_h or 0.0), "hours as printed by the run"
                if name in seen:
                    continue
                seen.add(name)
                out.append(sr.StrategyDef(
                    name=name, asset_class=sr.AssetClass.EQUITY_SWING,
                    categories=(sr.TradeCategory.SHORT_SELL if "__short__" in name else sr.TradeCategory.SWING,), timeframe="1d",
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"] or 0.0), pfgross=float(m["pfgross"] or 0.0), win_rate_pct=float(m["win_pct"]),
                                       n_trades=int(m["n"]), avg_held_hrs=hrs, avg_held_bars=None if bars is None else float(bars), avg_held_raw_unit=raw_unit,
                                       universe="NSE full universe", run_ref=ref),
                    source=src,
                    evidence=f"{ref}: PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, n={m['n']}, avg_hold {bars} 1d bars (run's raw avg_held_hours {raw_h}; normalized to market hours = bars x {sr.TRADING_HOURS_PER_DAY}), exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}",
                    notes=f"main.py-function replay of {r['tag']} ({r.get('mode') or r.get('spec')}); replaces nothing, research tag stays. n=0 means the detector found no trade (not evidence of edge)."))
            except Exception:
                continue
    return out
