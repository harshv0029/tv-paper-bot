"""B-1485: turn an oneil-nonoverlap.yml band_cap=trail result file (results keyed by band tag) into the MAIN_REPLAY_RUNS
row shape scripts/gen_swing_exit_variants.py reads: one row per (wired O'Neil tag, band_cap mode) with pooled metrics.
Only pooled tags (no _segis/_segoos) whose name equals swing_bandcap.band_tag(wired, mode) are kept.
Usage: python3 scripts/oneil_bandcap_to_main_replay.py <results.json> <out.json> <run_id>"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def convert(results: dict, wired_tags, run_id: str) -> dict:
    import swing_bandcap as sb
    rows = []
    for w in sorted(wired_tags):
        for mode in ("live",) + sb.TRAIL_MODES:
            bt = sb.band_tag(w, mode)
            r = results.get(bt)
            if not r or r.get("pfnet") is None:
                continue
            rows.append({"tag": bt, "wired_tag": w, "band_cap": mode, "run_id": run_id,
                         "metrics": {k: r.get(k) for k in ("n", "pfnet", "pfgross", "win_pct", "avg_net_pct")}
                         | {"avg_held_bars": r.get("avg_hold_bars")}})
    return {"source": f"oneil-nonoverlap.yml run {run_id} (band_cap=trail, strict FIFO, cost 0.008)", "rows": rows}


def main(argv):
    import main as m
    src, out, rid = argv[1], argv[2], argv[3]
    res = json.load(open(src))["results"]
    wired = [t for t in m._STRATEGY_TAG_TO_REGISTRY_NAME if t.startswith("oneil") and t.split("__")[3:4] in (["1d"], ["1w"])]
    d = convert(res, wired, rid)
    with open(out, "w") as f:
        json.dump(d, f, indent=1)
    print(f"{len(d['rows'])} rows for {len({r['wired_tag'] for r in d['rows']})} wired tags -> {out}")


if __name__ == "__main__":
    main(sys.argv)
