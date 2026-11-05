"""B-1472 (b) (2026-11-05 IST): registers oneil-replay.yml run 41958449455 (families=cup: oneil_cup_handle, oneil_saucer,
oneil_cup_nohandle, oneil_double_bottom; 1d + 1w; full NSE via main._load_nse_universe_from_file(), 2723 listed, 2173 1d /
1957 1w loaded; cost 0.8% round trip; REAL main.py code: signals main.oneil_signal_at -> main.oneil_pattern_signal_array,
stop main.oneil_stop_price, exit main.oneil_exit_bar / oneil_trail_stop). Raw: docs/backtest_data/oneil_pattern_replay_41958449455.json
(1,296 rows, every one registered, pass or fail).

Each row is its OWN tag: the research tag with a `srcmain` param token (a new measurement = a new token, never a rename;
the research-harness rows stay untouched). The replay is one full-period, full-universe pass with no symbol holdout, so
its PFnet IS the pooled number (2026-11-05 pooled rule). Caveat kept in evidence: rs80 cells rank RS per shard (about a
quarter of the universe), so their numbers are approximate and they are not wired. Viability stays derived at read time."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
RUN_ID = "41958449455"
_FN = f"oneil_pattern_replay_{RUN_ID}.json"
_SRC = ("main.oneil_signal_at / main.oneil_pattern_signal_array + main.oneil_stop_price + main.oneil_exit_bar "
        "(scripts/oneil_replay.py, use_main) ")


def srcmain_tag(tag: str) -> str:
    """Insert the `srcmain` token into the params field, keeping tokens in alphabetical order."""
    p = tag.split("__")
    p[4] = "_".join(sorted(p[4].split("_") + ["srcmain"]))
    return "__".join(p)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        d = json.load(open(os.path.join(_DIR, _FN)))
    except Exception:
        return out
    for r in d.get("rows", []):
        m, name = r["metrics"], r["tag"]
        tag = r.get("research_tag") or name
        if name in seen:
            continue
        seen.add(name)
        tf = tag.split("__")[3]
        bars = m.get("avg_held_bars")
        per_day = sr.TRADING_HOURS_PER_DAY * (5 if tf == "1w" else 1)
        ref = f"oneil-replay.yml run {RUN_ID} (2026-11-05 IST, full NSE, cost 0.8%, REAL main.py fns, pooled full period)"
        ex = m.get("exit_reasons")
        rs_note = "; RS rank per shard (approximate), not wired" if "rs80" in tag else ""
        out.append(sr.StrategyDef(
            name=name, asset_class=sr.AssetClass.EQUITY_SWING, categories=(sr.TradeCategory.SWING,), timeframe=tf,
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(
                pfnet=float(m["pfnet"]), pfgross=float(m.get("pfgross") or 0.0), win_rate_pct=float(m.get("win_pct") or 0.0),
                n_trades=int(m["n"]), avg_held_hrs=None if bars is None else float(bars) * per_day,
                avg_held_bars=None if bars is None else float(bars), avg_held_raw_unit=f"{tf} bars" if bars is not None else "",
                universe=f"NSE full universe ({m.get('universe', '')})", run_ref=ref),
            source=_SRC + f"; research tag {tag}",
            evidence=(f"{ref}: raw docs/backtest_data/{_FN}: PFnet {m['pfnet']}, gross {m.get('pfgross')}, win {m.get('win_pct')}%, "
                      f"n={m['n']}, hold {bars} {tf} bars, PFnet ex-top5 {m.get('pfnet_ex_top5')}, top5 share {m.get('top5_share')}, "
                      f"symbols {m.get('syms_traded')}" + (f"; exits {json.dumps(ex, separators=(',', ':'))}" if ex else "")
                      + rs_note),
            notes=f"B-1472 (b) main.py-calling O'Neil pattern replay of {tag}."))
    return out
