"""Registers class-A-unwired-replay run 38149302930 (2026-10-11 IST, cost 0.8%, 1d bars) from the committed raw JSON
docs/backtest_data/class_a_replay_run_38149302930.json (nothing trimmed there).  Minervini lab variants are replayed with the
real main.minervini_vcp_entry_signal (exits ported from scripts/minervini_lab.py) as new `v2` tags; sector-rotation short
cells are registered at the conservative gap_aware stop fill (stop-fill PFnet is kept in evidence + raw JSON).  Each tag is
its own row; viability is derived at read time from pfnet; nothing is wired.  avg_held is in daily bars."""
import json
import os

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", "class_a_replay_run_38149302930.json")
_REF = "class-a-unwired-replay.yml run 38149302930 (2026-10-11 IST, cost 0.8%, 1d)"


def _mk(tag, cat, m, uni, src, ev, notes):
    return sr.StrategyDef(
        name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None,
        metrics=sr.Metrics(
            pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0.0), win_rate_pct=float(m["win_pct"]),
            n_trades=int(m["n"]), avg_held_bars=float(m["avg_held_bars"]), avg_held_hrs=float(m["avg_held_bars"]) * sr.TRADING_HOURS_PER_DAY,
            universe=uni, run_ref=_REF),
        source=src, evidence=ev, notes=notes)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}  # never re-register an existing tag
    try:
        d = json.load(open(_FN))
    except Exception:
        return out
    for k, v in d.items():
        try:
            if v.get("metrics"):
                m = v["metrics"]
                tag = v["tag_replay_v2"]
                if tag in seen or not m.get("n") or m.get("pfnet") is None:
                    continue
                seen.add(tag)
                out.append(_mk(
                    tag, sr.TradeCategory.SWING, m, f"full NSE, {v.get('n_symbols')} symbols with data",
                    "main.minervini_vcp_entry_signal (real) + exits ported from scripts/minervini_lab.py",
                    f"{_REF}: PFnet {m['pfnet']:.3f} (gross {m['pfgross']:.3f}), win {m['win_pct']}%, n={m['n']}, "
                    f"avg_hold {m['avg_held_bars']} bars; exits {json.dumps(m.get('exit_reasons'), separators=(',', ':'))}",
                    "Class A Minervini lab variant replayed on the real entry fn; exit logic is a lab port so wiring needs "
                    "an exit port into main.py + SL on every trade. Viability derived from PFnet vs PFNET_LIVE_FLOOR."))
            elif v.get("cells"):
                for tag, c in v["cells"].items():
                    g = c["by_stop_fill"]["gap_aware"]
                    if tag in seen or not g.get("n") or g.get("pfnet") is None:
                        continue
                    seen.add(tag)
                    s = c["by_stop_fill"]["stop"]
                    out.append(_mk(
                        tag, sr.TradeCategory.SHORT_SELL, g, f"full NSE, {v.get('universe_size')} symbols",
                        "scripts/class_a_unwired_replay.py sector_short",
                        f"{_REF}: gap_aware PFnet {g['pfnet']:.3f} (gross {g['pfgross']:.3f}), win {g['win_pct']}%, n={g['n']}, "
                        f"avg_hold {g['avg_held_bars']} bars; stop-fill PFnet {s['pfnet']:.3f} n={s['n']}; "
                        f"exits {json.dumps(g.get('exit_reasons'), separators=(',', ':'))}",
                        "Sector-rotation fade short mirror, registered at the conservative gap_aware stop fill. Short engine "
                        "wiring needs a main.py port; SL on every trade."))
        except Exception:
            continue
    return out
