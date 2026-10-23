"""B-420: shared summary/output helper for legacy research replays that never recorded a bar-count hold.

Output code only. It never changes which trades are taken or how they exit; it reads the finished trade dicts.

* attach_held_bars(trades, ts_arr): holding period in MARKET BARS = bar-index distance between the entry bar and the
  exit bar of the same fetched series (an overnight gap or a weekend counts as one bar step, never as wall-clock time).
  `ts_arr` is the ascending per-bar timestamp array the replay used for entry_ts/exit_ts (same unit, same offset).
* summarize(tag, trades, universe, run_id, bar_minutes): n, win_pct, pfnet, pfgross, avg_held_bars,
  avg_held_hrs (= avg_held_bars * bar_minutes / 60), exit-reason breakdown, universe, run_id.
* write_summary(rows, out_dir): summary.json + summary.tsv, and prints one line per row.
"""
import json
import os

import numpy as np

COLUMNS = ("tag", "n", "win_pct", "pfnet", "pfgross", "avg_held_bars", "avg_held_hrs", "exit_reasons",
           "universe", "run_id")


def held_bars_from_ts(ts_arr, entry_ts, exit_ts):
    ts_arr = np.asarray(ts_arr, dtype=float)
    return int(np.searchsorted(ts_arr, float(exit_ts), side="left") - np.searchsorted(ts_arr, float(entry_ts), side="left"))


def attach_held_bars(trades, ts_arr):
    for t in trades:
        t["held_bars"] = held_bars_from_ts(ts_arr, t["entry_ts"], t["exit_ts"])
    return trades


def _pf(pnls):
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p <= 0)
    if gl > 0:
        return round(gw / gl, 4)
    return None if gw == 0 else float("inf")


def summarize(tag, trades, universe, run_id=None, bar_minutes=5):
    run_id = run_id if run_id is not None else os.environ.get("GITHUB_RUN_ID", "")
    n = len(trades)
    reasons = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    held = [t["held_bars"] for t in trades if t.get("held_bars") is not None]
    avg_bars = (sum(held) / len(held)) if held else None
    return {
        "tag": tag, "n": n,
        "win_pct": round(100.0 * sum(1 for t in trades if t["net_pnl"] > 0) / n, 2) if n else None,
        "pfnet": _pf([t["net_pnl"] for t in trades]) if n else None,
        "pfgross": _pf([t["gross_pnl"] for t in trades]) if n else None,
        "avg_held_bars": round(avg_bars, 2) if avg_bars is not None else None,
        "avg_held_hrs": round(avg_bars * bar_minutes / 60.0, 3) if avg_bars is not None else None,
        "exit_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "universe": universe, "run_id": str(run_id), "bar_minutes": bar_minutes,
    }


def write_summary(rows, out_dir="b420_out"):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(rows, f, indent=1)
    with open(os.path.join(out_dir, "summary.tsv"), "w") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(json.dumps(r[c]) if c == "exit_reasons" else str(r[c]) for c in COLUMNS) + "\n")
    print("\n=== B-420 summary (avg hold in market bars, not wall-clock) ===")
    for r in rows:
        print(f"  {r['tag']}: n={r['n']} win%={r['win_pct']} PFnet={r['pfnet']} PFgross={r['pfgross']} "
              f"avg_held_bars={r['avg_held_bars']} avg_held_hrs={r['avg_held_hrs']} exits={r['exit_reasons']} "
              f"universe={r['universe']} run_id={r['run_id']}")
    return rows
