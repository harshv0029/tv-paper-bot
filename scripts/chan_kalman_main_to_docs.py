"""B-1262: turn an intraday-flatten-rerun.yml `chan_kalman_main` merge (flat_results.json) into the committed
docs/backtest_data/chan_kalman_main_replay_run_<RUN_ID>.json that strategy_registry_chan_main + main._replay_verified_tags read.

The replay itself already exists: workflow intraday-flatten-rerun.yml (families=["chan_kalman_main"]) drives
scripts/intraday_flatten_rerun.py, which calls the REAL main.chan_kalman_band_short_entry_signal / _exit_reason bar by bar on the
full universe (main._load_nse_universe_from_file()), cost main.ROUND_TRIP_COST_PCT (or cost_pct input), 15:15 IST forced flat.
Only this conversion step was manual. Tags are renamed band -> band_mr (own variant, never colliding with the research `band`
tags). Every measured field is kept (n, win_pct, pfnet, pfgross, avg_held_hours, exit_reasons); viability is derived at read time.

  python3 scripts/chan_kalman_main_to_docs.py flat_results.json RUN_ID [OUT_DIR]
"""
import json
import os
import sys

KEEP = ("n", "win_pct", "pfnet", "pfgross", "avg_held_bars", "exit_reasons")


def convert(results, run_id, cost_pct=None):
    rows, meta = [], {}
    for key, r in sorted(results["results"].items()):
        if r.get("family") != "chan_kalman_main":
            continue
        tag = r["tag"].replace("chan_kalman__band__", "chan_kalman__band_mr__", 1)
        m = {k: r[k] for k in KEEP if k in r}
        m["avg_held_hours"] = r.get("avg_held_hrs")
        rows.append({"tag": tag, "interval": r.get("interval"), "metrics": m})
    for g in results.get("groups", []):
        if g.get("family") == "chan_kalman_main":
            meta = {"symbols": meta.get("symbols", 0) + g["symbols"], "cost_round_trip": g.get("cost_round_trip")}
    cr = meta.get("cost_round_trip")
    return {"cost_round_trip_pct": round(cr * 100, 4) if cr is not None else cost_pct,
            "family": "chan_kalman_main", "run_id": run_id, "symbols": meta.get("symbols"),
            "note": "intraday-flatten-rerun.yml chan_kalman_main, real main.py chan_kalman_band_short_* functions, 15:15 IST forced flat",
            "rows": rows}


if __name__ == "__main__":
    res = json.load(open(sys.argv[1]))
    out = convert(res, sys.argv[2])
    d = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data")
    p = os.path.join(d, f"chan_kalman_main_replay_run_{sys.argv[2]}.json")
    json.dump(out, open(p, "w"), indent=1)
    print("wrote", p, len(out["rows"]), "rows")
