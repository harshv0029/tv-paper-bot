"""B-1417 (2026-10-30 IST): registers the live-mode (band_cap=live, `rsbandfloor`) rows of swing-bandcap-replay.yml run
40952500265 (full NSE via main._load_nse_universe_from_file(), cost 0.8% round trip, REAL main.py entry/exit fns through
scripts/swing_bandcap_replay.py). The live model = what Kotak actually rests: the strategy's own stop raised to the 10% daily
band floor (prev_close x 0.9 x 1.003; ceiling prev_close x 1.1 x 0.997 for a short), triggered intraday on the low/high.

Each `band_tag` is its own research row (naming grammar: a param change = a new tag, never a rename). The band_cap=off rows of
the same run are NOT registered here (they re-measure tags that already have registry rows; their numbers stay in the raw
JSON docs/backtest_data/swing_bandcap_run_40952500265.json). Nothing here changes a live gate: the live tags still map to
their existing registry names in main._STRATEGY_TAG_TO_REGISTRY_NAME. Viability stays derived at read time.

Hold units: avg_held_bars is the replay's own bar count; macddiv cells run on 1h bars (1 market hour per bar), every other
family on DAILY bars (the oneil `1w` cells are replayed on daily bars, see the workflow header), x TRADING_HOURS_PER_DAY."""
import json
import os

import strategy_registry as sr

_FN = "swing_bandcap_run_40952500265.json"
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data", _FN)
_REF = "swing-bandcap-replay.yml run 40952500265 (2026-10-30 IST, band_cap=live, full NSE, cost 0.8%, REAL main.py fns)"
_SRC = "scripts/swing_bandcap_replay.py + scripts/swing_bandcap.py (band_cap=live resting-stop model) over the family's main.py fns"


def _category(row: dict):
    if row.get("family") == "short_swing" or "__short__" in row["tag"]:
        return (sr.TradeCategory.SHORT_SELL,)
    return (sr.TradeCategory.SWING,)


def _tf(row: dict) -> str:
    parts = row["tag"].split("__")
    return parts[3] if len(parts) > 3 else "1d"


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(_PATH))
    except Exception:
        return out
    for r in d.get("rows", []):
        try:
            name, m, off = r["band_tag"], r["live"], r.get("off") or {}
            if name in seen or m.get("pfnet") is None:
                continue
            seen.add(name)
            bars = m.get("avg_held_bars")
            per_bar = 1.0 if r.get("family") == "macddiv" else sr.TRADING_HOURS_PER_DAY
            unit = "1h bars" if r.get("family") == "macddiv" else "1d bars"
            out.append(sr.StrategyDef(
                name=name, asset_class=sr.AssetClass.EQUITY_SWING, categories=_category(r), timeframe=_tf(r),
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0), win_rate_pct=float(m.get("win_pct") or 0),
                    n_trades=int(m["n"]), avg_held_hrs=None if bars is None else float(bars) * per_bar,
                    avg_held_bars=None if bars is None else float(bars), avg_held_raw_unit=unit if bars is not None else "",
                    universe=f"NSE full universe ({r.get('n_symbols')} symbols with data)", run_ref=_REF),
                source=_SRC,
                evidence=(f"{_REF}: raw docs/backtest_data/{_FN}: live PFnet {m['pfnet']}, gross {m.get('pfgross')}, win "
                          f"{m.get('win_pct')}%, n={m['n']}, avg net {m.get('avg_net_pct')}%, hold {bars} {unit}, exits "
                          f"{json.dumps(m.get('exit_reasons'), separators=(',', ':'))}. Same run band_cap=off of {r['tag']}: "
                          f"PFnet {off.get('pfnet')}, gross {off.get('pfgross')}, win {off.get('win_pct')}%, n={off.get('n')}, "
                          f"hold {off.get('avg_held_bars')} {unit}."),
                notes=(f"B-1417 live resting-stop (10% band floor, intraday trigger) replay of {r['tag']}. Research row; "
                       f"the off tag's own registry row stays unchanged.")))
        except Exception:
            continue
    return out
