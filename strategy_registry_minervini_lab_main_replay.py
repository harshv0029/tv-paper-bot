"""B-1467: Minervini lab main.py-calling replay results (scripts/minervini_lab_main_replay_job.py on
sector-rotation-backtest.yml, entry main.minervini_vcp_entry_signal, exits main.minervini_lab_simulate_trade). One position
per symbol, cost 0.8% round trip, max hold 60 bars. Each row registers three strategies, never pooled: the pooled tag and its IS / OOS segments
(_segis / _segoos appended to the params field). Every row is registered whatever its result."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
SRC = "scripts/minervini_lab_main_replay_job.py"
# results file -> GitHub Actions run id that produced it
RUNS = {
    "minervini_lab_main_replay_long.json": 41887002039,
    "minervini_lab_main_replay_short.json": 41888716565,
    "minervini_lab_main_replay_baseline_long.json": 41889377598,
    "minervini_lab_main_replay_long_h30.json": 41891143316,
    "minervini_lab_main_replay_long_h40.json": 41891148569,
    "minervini_lab_main_replay_short_h30.json": 41895945064,
    "minervini_lab_main_replay_short_h40.json": 41895952533,
}


def _seg_tag(tag, seg):
    assert tag.endswith("__v1"), tag
    return tag[: -len("__v1")] + f"_seg{seg}__v1"


def _defs(fn, run_id, seen):
    p = os.path.join(_DIR, fn)
    if not os.path.exists(p):
        return []
    d = json.load(open(p))
    uni = (f"{d.get('universe')}: {d.get('n_symbols')} of {d.get('universe_requested')} symbols with data, IS/OOS split "
           f"{d.get('is_oos_split_date')}, one position per symbol, cost {d.get('cost_round_trip_pct')}% round trip")
    out = []
    tf = d.get("tf", "1d")
    for tag0, r in (d.get("rows") or {}).items():
        r = dict(r, tag=tag0, tf=tf)
        m0 = r["metrics"]
        for seg, m in (("pooled", m0), ("is", m0.get("is") or {}), ("oos", m0.get("oos") or {})):
            tag = r["tag"] if seg == "pooled" else _seg_tag(r["tag"], seg)
            if tag in seen or (seg != "pooled" and not m.get("n")):  # pooled always kept, even n=0
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if r["direction"] == "short" else sr.TradeCategory.SWING
            ev = (f"B-1467 minervini lab main replay run {run_id} ({fn}) [{seg}]: n={m['n']} pfnet={m['pfnet']} "
                  f"pfgross={m['pfgross']} win={m['win_pct']}% avg_hold={m['avg_held_bars']}bars (replay hours {m.get('avg_held_hours')}) "
                  f"avg_net={m.get('avg_net_pct')}%; source_tag={r.get('source_tag')}; "
                  f"exits={json.dumps(m.get('exit_reasons'), separators=(',', ':'))}")
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe=r["tf"],
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(m["pfnet"] or 0.0), pfgross=float(m["pfgross"] or 0.0),
                                   win_rate_pct=float(m["win_pct"] or 0.0), n_trades=int(m["n"]),
                                   avg_held_bars=float(m["avg_held_bars"] or 0.0),
                                   avg_held_hrs=float(m["avg_held_bars"] or 0.0) * sr.market_hours_per_bar(r["tf"]),
                                   universe=uni,
                                   run_ref=f"sector-rotation-backtest.yml run {run_id}"),
                source=SRC, evidence=ev,
                notes=(f"minervini lab main.py replay {r['tf']} variant={r.get('variant')} ({seg}); pooled/_segis/_segoos are separate "
                       "strategies. Viability derived vs PFNET_LIVE_FLOOR at read time."
                       + (f" CAUTION: {r['note']}" if r.get("note") else ""))))
    return out


def build():
    seen = {x.name for x in sr.REGISTRY}
    out = []
    for fn, rid in RUNS.items():
        out += _defs(fn, rid, seen)
    return out
