"""Registers main.py-calling full-universe replays (B-1220): chan_gap BUY-on-gap long (run 38501321543, chan-gap-main-replay.yml) in the BUY
category, and the PARTIAL pl1d short replay (run 38501324353, 2 of the cells read from the job log, rest owed from artifact
pl1d-short-main-replay-results id 11865767574) in SHORT_SELL. Each result is its own tag: the original tag with `_mr` appended to the
variant field (same convention as strategy_registry_main_replay.mr_name); the research tag stays registered unchanged, never overwritten.
Research entries (entry_fn=None). main._replay_verified_tags() reads these JSONs directly and clears the original chan_gap tags from
REPLAY_OWED_TAGS (PFnet >= floor, n >= 30); both pl1d short cells are below the floor, so nothing opens for them. All raw fields kept."""
import json
import os

import strategy_registry as sr
from strategy_registry_main_replay import mr_name

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("chan_gap_main_replay_run_38501321543.json", "chan-gap-main-replay.yml run 38501321543 (1d, cost 0.8%, main.py functions, ATR stop attached)",
     "scripts/chan_gap_main_replay.py", sr.AssetClass.EQUITY_INTRADAY, sr.TradeCategory.BUY),
    ("chan_gap_main_replay_run_39599591455.json", "chan-gap-main-replay.yml run 39599591455 (B-1331: live capped-5% stop + fit-in-5% rule; 1d, cost 0.8%, main.py functions)",
     "scripts/chan_gap_long_main_replay.py", sr.AssetClass.EQUITY_INTRADAY, sr.TradeCategory.BUY),
    ("pl1d_short_main_replay_run_38501324353_partial.json", "pl1d-short-main-replay.yml run 38501324353 (1d, cost 0.8%, main.py functions; PARTIAL: 2 cells from the job log)",
     "scripts/pl1d_short_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SHORT_SELL),
    ("chan_gap_short_main_replay_run_38502123279.json", "chan-gap-short-main-replay.yml run 38502123279 (1d, cost 0.8%, main.py functions; only the atr1d5 cell was emitted)",
     "scripts/chan_gap_main_replay.py", sr.AssetClass.EQUITY_INTRADAY, sr.TradeCategory.SHORT_SELL),
    ("pl1d_long_main_replay_run_38506928246.json", "pl1d-main-replay.yml run 38506928246 (1d, cost 0.8%, main.py functions pl1d_long_entry_signal/pl1d_exit_reason, ATR stop attached)",
     "scripts/pl1d_main_replay.py", sr.AssetClass.EQUITY_SWING, sr.TradeCategory.SWING),
)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, ref, src, ac, cat in _RUNS:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        for r in d.get("rows", []):
            try:
                m = r["metrics"]
                name = mr_name(r["tag"])
                if "_mr__" not in name:  # tags whose direction token is missing never get silently renamed
                    continue
                # grammar: the `_mr` marker must sit on the variant field, e.g. buy_on_gap_mr
                if name in seen:
                    continue
                seen.add(name)
                bars = m.get("avg_held_bars")
                hrs = m.get("avg_held_hours")
                if hrs is None and bars is not None:  # B-420: derive market hours from the SAME row's raw 1d bar count (never guessed)
                    hrs = float(bars) * sr.TRADING_HOURS_PER_DAY
                out.append(sr.StrategyDef(
                    name=name, asset_class=ac, categories=(cat,), timeframe="1d", status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=float(m["pfnet"]), pfgross=float(m["pfgross"]), win_rate_pct=float(m["win_pct"]),
                                       n_trades=int(m["n"]), avg_held_hrs=None if hrs is None else float(hrs),
                                       avg_held_bars=None if bars is None else float(bars),
                                       avg_held_raw_unit="1d bars" if bars is not None else "",
                                       universe="NSE full universe", run_ref=ref),
                    source=src,
                    evidence=f"{ref}: raw docs/backtest_data/{fn}: PFnet {m['pfnet']}, gross {m['pfgross']}, win {m['win_pct']}%, n={m['n']}, hold {hrs}h, exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}",
                    notes=f"main.py-function replay of {r['tag']} in the {cat.name} category; the research tag stays registered unchanged. "
                          + ("Live entry path exists (CHAN_GAP_LONG_CELLS / _chan_gap_long_try_entry, ATR stop always attached, B-982)." if cat == sr.TradeCategory.BUY
                             else "Live entry path exists (PL1D_CELLS / _pl1d_try_entry swing engine, pl1d_stop_loss ATR stop always attached, resting SL placed and entry unwound on SL failure, B-983)." if cat == sr.TradeCategory.SWING
                             else ("Live short path: CHAN_GAP_SHORT_TAG, intraday short engine, flat by 15:10, ATR stop attached (B-981)." if "short_on_gap" in r["tag"]
                                   else "Below PFNET_LIVE_FLOOR in both cells; remaining cells owed from the artifact."))))
            except Exception:
                continue
    return out
