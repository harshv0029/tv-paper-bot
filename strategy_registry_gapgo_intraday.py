"""Registers intraday-gap-and-go-research.yml run 38277225522 (5m, 60d, full NSE universe, cost 0.8%, B-45): 4 long ATR cells and
4 short-mirror cells. Raw rows docs/backtest_data/intraday_gap_and_go_5m_run_38277225522.json (incl. trim1, exit reasons, day_stats).
The 4 SHORT cells have n=0 because of a harness bug (long-only _target_move_pct used for shorts), NOT because the setup never occurs:
they are kept registered with their zeros and a rerun is owed under a new tag (backlog B-876). Research-only, entry_fn=None; viability
is derived at read time from PFnet vs PFNET_LIVE_FLOOR, nothing wired live.

B-876 (run 38280746427, same workflow after the `_target_move_pct_short` sign fix): 8 `__v2` tags (4 long, 4 short, now n>0 for shorts).
Raw rows docs/backtest_data/intraday_gap_and_go_5m_v2_run_38280746427.json. The v1 entries above stay registered unchanged.

B-45 15m (60d, full NSE universe, cost 0.8%): run 38280065474 = 8 `15m__...__v1` tags (4 long real; 4 short n=0 from the same pre-fix sign bug, kept with
zeros) in docs/backtest_data/intraday_gap_and_go_15m_run_38280065474.json; run 38285436608 = 8 `15m__...__v2` tags (long reproduces v1, short n=580 after the fix)
in docs/backtest_data/intraday_gap_and_go_15m_v2_run_38285436608.json. v1 and v2 stay separate tags."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_RUNS = (
    ("intraday_gap_and_go_5m_run_38277225522.json", "intraday-gap-and-go-research.yml run 38277225522 (5m, 60d, cost 0.8%, full NSE universe)", True),
    ("intraday_gap_and_go_5m_v2_run_38280746427.json", "intraday-gap-and-go-research.yml run 38280746427 (5m, 60d, cost 0.8%, full NSE universe, short sign fix, B-876)", False),
    ("intraday_gap_and_go_15m_run_38280065474.json", "intraday-gap-and-go-research.yml run 38280065474 (15m, 60d, cost 0.8%, full NSE universe)", True),
    ("intraday_gap_and_go_15m_v2_run_38285436608.json", "intraday-gap-and-go-research.yml run 38285436608 (15m, 60d, cost 0.8%, full NSE universe, short sign fix, B-45)", False),
)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, _REF, zero_short_bug in _RUNS:
        out.extend(_build_one(fn, _REF, zero_short_bug, seen))
    return out


def _build_one(fn, _REF, zero_short_bug, seen):
    out = []
    try:
        d = json.load(open(os.path.join(_DIR, fn)))
    except Exception:
        return out
    for r in d.get("rows", []):
        try:
            tag = r["tag"]
            if tag in seen:
                continue
            seen.add(tag)
            short = "__short__" in tag
            tf = "15m" if "__15m__" in tag else "5m"
            min_per_bar = 15.0 if tf == "15m" else 5.0
            cat = sr.TradeCategory.SHORT_SELL if short else sr.TradeCategory.BUY
            pfn = r["pfnet"] if r["pfnet"] is not None else 0.0
            pfg = r["pf_gross"] if r["pf_gross"] is not None else 0.0
            note = ("n=0: harness bug (long-only _target_move_pct on shorts rejected every candidate), not evidence of no edge; rerun owed (B-876). "
                    if (short and zero_short_bug) else "")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(cat,), timeframe=tf,
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(pfn), pfgross=float(pfg), win_rate_pct=float(r["win_pct"]),
                                   n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * min_per_bar / 60.0,
                                   universe="NSE full universe", run_ref=_REF),
                source="scripts/intraday_gap_and_go_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']}, gross {r['pf_gross']}, trim1 {r['pfnet_trim1']}, win {r['win_pct']}%, n={r['n']}, "
                         f"avg_hold {r['avg_hold_bars']} bars ({tf}); top5 net ret % {r['top5_net_ret_pct']}; exits {json.dumps(r['exit_reasons'], separators=(',', ':'))}",
                notes=note + f"Same-day intraday gap-and-go (2% gap, hold above open, vol 1.5x, 30-min entry window), ATR stop on every trade, flat by 15:20 IST; {tf} cell (5m and 15m both registered); research-only, entry_fn=None, nothing wired (B-45)."))
        except Exception:
            continue
    return out
