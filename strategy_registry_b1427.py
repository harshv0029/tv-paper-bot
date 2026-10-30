"""B-1427 (2026-10-30 IST): registers gap-and-go-exitfamily-replay.yml run 41013761661 (full NSE via
main._load_nse_universe_from_file(), 2678 symbols, cost 0.8% round trip, REAL main.py code through
scripts/gap_and_go_exitfamily_replay.py: entry main.gap_and_go_entry_signal, exit main.exitfamily_walk /
exitfamily_exit_reason, cells main.GAP_AND_GO_EXITFAMILY_CELLS). Raw: docs/backtest_data/gap_and_go_exitfamily_replay_41013761661.json.

Two rows per exit cell, each its own tag (naming grammar: a new measurement model = a new param token, never a rename):
  off  -> `rsintraday` tag: the cell's own stop triggered intraday on the low, no band floor (B-1413 precedent). The bare
          cell tag already holds the research-sim v2 metrics (run 40951289638) and is never overwritten.
  live -> `rsbandfloor` tag: the resting stop raised to the 10% daily band floor (what Kotak can hold). The live gate for
          the wired xroc cell reads its rsbandfloor row (main._STRATEGY_TAG_TO_REGISTRY_NAME).
The control (gap_and_go / gap_and_go__rsbandfloor) re-measures tags B-1417 already registered; kept in the JSON only.
Hold units: avg_held_bars = daily bars (trading days) x TRADING_HOURS_PER_DAY. pfgross was not in the relayed summary:
stored as 0.0 and flagged in evidence, to be completed from the run artifact. Viability stays derived at read time."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
RUN_ID = "41013761661"
_FN = f"gap_and_go_exitfamily_replay_{RUN_ID}.json"
_SRC = ("main.gap_and_go_entry_signal + main.exitfamily_walk / main.exitfamily_exit_reason (GAP_AND_GO_EXITFAMILY_CELLS) "
        "via scripts/gap_and_go_exitfamily_replay.py + scripts/swing_bandcap.py")


def _row_def(r: dict, mode: str):
    m = r[mode]
    name = r["off_tag"] if mode == "off" else r["band_tag"]
    other = r["live"] if mode == "off" else r["off"]
    bars = m.get("avg_held_bars")
    model = ("band_cap=off (cell stop on the intraday low, no band floor)" if mode == "off" else
             "band_cap=live (resting stop = max(cell stop, prev close x 0.9 x 1.003), intraday trigger)")
    ref = f"gap-and-go-exitfamily-replay.yml run {RUN_ID} (2026-10-30 IST, {model}, full NSE, cost 0.8%, REAL main.py fns)"
    ex = m.get("exit_reasons")
    return sr.StrategyDef(
        name=name, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe="1d",
        status=sr.StrategyStatus.RESEARCH, entry_fn=None,
        metrics=sr.Metrics(
            pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0.0), win_rate_pct=float(m["win_pct"]),
            n_trades=int(m["n"]), avg_held_hrs=None if bars is None else float(bars) * sr.TRADING_HOURS_PER_DAY,
            avg_held_bars=None if bars is None else float(bars), avg_held_raw_unit="1d bars" if bars is not None else "",
            universe=f"NSE full universe ({r.get('n_symbols')} symbols with data)", run_ref=ref),
        source=_SRC,
        evidence=(f"{ref}: raw docs/backtest_data/{_FN}: PFnet {m['pfnet']}, win {m['win_pct']}%, n={m['n']}, hold {bars} 1d "
                  f"bars; pfgross/avg_net not in the relayed summary (owed from the artifact)"
                  + (f"; exits {json.dumps(ex, separators=(',', ':'))}" if ex else "")
                  + f". Same run, other mode: PFnet {other.get('pfnet')}, win {other.get('win_pct')}%, n={other.get('n')}, "
                    f"hold {other.get('avg_held_bars')}. Control gap_and_go same run: off 1.136 / live 1.097."),
        notes=(f"B-1427 main.py-calling replay of exit cell {r['tag']} ({mode}). The bare tag's research-sim v2 row stays "
               f"unchanged." + (" LIVE GATE row for the wired gap_and_go xroc exit." if mode == "live" and "xroc" in name else "")))


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(os.path.join(_DIR, _FN)))
    except Exception:
        return out
    for r in d.get("rows", []):
        if r.get("control"):
            continue
        for mode in ("off", "live"):
            try:
                if (r.get(mode) or {}).get("pfnet") is None:
                    continue
                name = r["off_tag"] if mode == "off" else r["band_tag"]
                if name in seen:
                    continue
                seen.add(name)
                out.append(_row_def(r, mode))
            except Exception:
                continue
    return out
