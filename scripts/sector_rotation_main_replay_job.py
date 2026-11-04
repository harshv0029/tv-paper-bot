"""B-1467: run ONE sector_rotation_main_replay plan job through the generic sector-rotation-backtest.yml runner
(already on main), so the main.py-calling replay can run before sector-rotation-main-replay.yml reaches main.

Env (set by that workflow): TF = plan job name (1d, 1d_n200, 1h, 4h, 15m). ENTRY defaults to next_open.
Writes docs/backtest_data/sector_main_replay_<name>_<entry>.json (same schema as the matrix workflow's shards).
"""
import json, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sector_rotation_main_replay as smr  # noqa: E402


def main():
    import main as m
    import strategy_registry as r
    job = os.environ.get("TF", "1d")
    entry = os.environ.get("ENTRY", "next_open") or "next_open"
    plan = smr.build_plan(r.REGISTRY, set(m._STRATEGY_TAG_TO_REGISTRY_NAME.values()))
    j = next((x for x in plan["include"] if x["name"] == job), None)
    if j is None:
        raise SystemExit(f"no plan job {job!r}; have {[x['name'] for x in plan['include']]}")
    name = f"{job}_{entry}"
    os.environ.update({"TF": j["tf"], "UNI": j["uni"], "SECTOR_GROUPS": j["groups"], "ATRS": j["atrs"],
                       "ENTRY": entry, "NAME": name})
    smr.run()
    os.makedirs("docs/backtest_data", exist_ok=True)
    shutil.copy(f"out/sector_main_replay_{name}.json", f"docs/backtest_data/sector_main_replay_{name}.json")


if __name__ == "__main__":
    main()
