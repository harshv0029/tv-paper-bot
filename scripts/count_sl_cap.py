"""B-775: read-time count of registry tags with PFnet>=floor, hold<=N trading days and
planned SL% <= cap. Nothing is stored as a viability flag: everything is derived from
the registry metrics (+ optional sidecar of measured stop-% per tag).

The registry stores only the ATR multiple, not stop-%; measured stop-% comes from a
sidecar JSON {tag: median_stop_pct} written by research outputs (docs/backtest_data/
stop_pct.json). Tags with no measurement are reported as UNKNOWN, never guessed.
Usage: python3 scripts/count_sl_cap.py [--hold 5] [--cap 2.0] [--sidecar PATH]"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, ".")
import strategy_registry as sr  # noqa: E402


def count(hold_days=5.0, cap_pct=2.0, sidecar=None, registry=None, floor=None):
    floor = sr.PFNET_LIVE_FLOOR if floor is None else floor
    stops = {}
    if sidecar and pathlib.Path(sidecar).exists():
        stops = json.loads(pathlib.Path(sidecar).read_text())
    out = {"pass": [], "over_cap": [], "unknown_stop": [], "hold_unknown": []}
    for s in (registry if registry is not None else sr.REGISTRY):
        m = s.metrics
        if not m or m.pfnet is None or m.pfnet < floor:
            continue
        if m.avg_held_hrs is None:
            out["hold_unknown"].append(s.name)
            continue
        if m.avg_held_hrs / sr.TRADING_HOURS_PER_DAY > hold_days:
            continue
        st = stops.get(s.name)
        if st is None:
            out["unknown_stop"].append(s.name)
        elif st <= cap_pct:
            out["pass"].append(s.name)
        else:
            out["over_cap"].append(s.name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=5.0)
    ap.add_argument("--cap", type=float, default=2.0)
    ap.add_argument("--sidecar", default="docs/backtest_data/stop_pct.json")
    a = ap.parse_args()
    r = count(a.hold, a.cap, a.sidecar)
    print(f"viable & hold<={a.hold}d: pass(SL<={a.cap}%)={len(r['pass'])} "
          f"over_cap={len(r['over_cap'])} stop_unmeasured={len(r['unknown_stop'])} "
          f"hold_unrecorded={len(r['hold_unknown'])}")


if __name__ == "__main__":
    main()
