"""B-1467: chan_kalman v1 band main.py-calling replay results (scripts/chan_kalman_main_replay_job.py on
sector-rotation-backtest.yml, calling main.chan_kalman_band_v1_*). One position per symbol (per direction, or across
both sides for the _comb walk), cost 0.8% round trip, entry next open. Each row registers three strategies, never pooled: the pooled tag and its IS / OOS segments
(_segis / _segoos appended to the params field). Every row is registered whatever its result."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
SRC = "scripts/chan_kalman_main_replay_job.py"
# results file -> GitHub Actions run id that produced it
RUNS = {
    "chan_kalman_main_replay_1d.json": 41881365947,
    "chan_kalman_main_replay_1h.json": 41886040481,
}


def _seg_tag(tag, seg):
    assert tag.endswith("__v1"), tag
    return tag[: -len("__v1")] + f"_seg{seg}__v1"


def _defs(fn, run_id, seen):
    p = os.path.join(_DIR, fn)
    if not os.path.exists(p):
        return []
    d = json.load(open(p))
    uni = (f"{d.get('universe_requested')}: {d.get('symbols_kept')} of {d.get('symbols_seen')} symbols kept, IS/OOS cut "
           f"{d.get('is_oos_cutoff_utc')} UTC, one position per symbol, cost {d.get('cost_round_trip_pct')}% round trip")
    out = []
    for r in d.get("rows", []):
        m0 = r["metrics"]
        for seg, m in (("pooled", m0), ("is", m0.get("is") or {}), ("oos", m0.get("oos") or {})):
            tag = r["tag"] if seg == "pooled" else _seg_tag(r["tag"], seg)
            if tag in seen or (seg != "pooled" and not m.get("n")):  # pooled always kept, even n=0
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if r["direction"] == "short" else sr.TradeCategory.SWING
            ev = (f"B-1467 chan_kalman v1 band main replay run {run_id} ({fn}) [{seg}]: n={m['n']} pfnet={m['pfnet']} "
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
                notes=(f"chan_kalman v1 band main.py replay {r['tf']} walk={r.get('walk')} ({seg}); pooled/_segis/_segoos are separate "
                       "strategies. Viability derived vs PFNET_LIVE_FLOOR at read time.")))
    return out


def build():
    seen = {x.name for x in sr.REGISTRY}
    out = []
    for fn, rid in RUNS.items():
        out += _defs(fn, rid, seen)
    return out
