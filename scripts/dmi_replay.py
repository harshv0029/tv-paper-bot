"""Full-universe replay for the `dmi_adx` family (backlog B-11): variants cross / adx_gate /
adx_turn, each long and short. Calls the REAL main.dmi_scan; bookkeeping,
costs and sizing are shared with scripts/fvg3c_replay.py (same cost model).
Modes: shard | aggregate. Env: SHARD_INDEX, SHARD_COUNT, INTERVAL, PERIOD, GRID.
One result row per strategy tag: dmi_adx__<variant>__<dir>__<tf>__<params>__v1.
"""
import glob
import importlib.util
import json
import os
import pathlib
import sys

sys.path.insert(0, ".")
import main as m  # noqa: E402

_spec = importlib.util.spec_from_file_location("fvg3c_replay", pathlib.Path(__file__).resolve().parent / "fvg3c_replay.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

ABBR = {"period": "p", "adx_min": "am", "adx_turn_level": "tl", "stop_atr": "sa", "rr": "rr", "max_hold_bars": "mh"}
VARIANT_DIR = tuple((v, d) for v in m.DMI_VARIANTS for d in ("long", "short"))


def cell_tag(variant, direction, tf, params):
    full = dict(m.DMI_DEFAULT_PARAMS); full.update(params)
    ps = "_".join(f"{ABBR[k]}{fr._fmt(full[k])}" for k in sorted(full))
    return f"dmi_adx__{variant}__{direction}__{tf}__{ps}__v1"


def run_shard():
    idx, count = int(os.environ["SHARD_INDEX"]), int(os.environ["SHARD_COUNT"])
    interval, period = os.environ.get("INTERVAL", "5m"), os.environ.get("PERIOD", "60d")
    grid = json.loads(os.environ.get("GRID", "[{}]"))
    cells = [(v, d, g) for g in grid for v, d in VARIANT_DIR]
    symbols = sorted(set(m._load_nse_universe_from_file()))[idx::count]
    stride = max(1, int(os.environ.get("SAMPLE_EVERY", "1")))  # >1 = cheap screening pilot (every Nth symbol); 1 = FULL universe
    symbols = symbols[::stride]
    print(f"--- shard {idx}/{count}: {len(symbols)} symbols, {len(cells)} cells, {interval}/{period} ---")
    out = {cell_tag(v, d, interval, g): [] for v, d, g in cells}
    fetched = 0
    for sym in symbols:
        try:
            raw = m.fetch_ohlc(sym, period, interval)
        except Exception as e:
            print(f"SKIP {sym}: {e}"); continue
        if raw is None or len(raw) < 60:
            continue
        fetched += 1
        df, sessions, mins, ts_arr = fr.prep(raw)
        for v, d, g in cells:
            try:
                scanner = lambda frame, prm, sess, _v=v, _d=d: m.dmi_scan(frame, _v, _d, prm, sessions=sess)  # noqa: E731
                out[cell_tag(v, d, interval, g)].extend(
                    fr.replay_cell(sym, df, v, d, g, sessions, mins, ts_arr, scanner=scanner, defaults=m.DMI_DEFAULT_PARAMS))
            except Exception as e:
                print(f"ERROR {sym} {v}: {e}")
    with open("shard_result.json", "w") as f:
        json.dump({"shard": idx, "fetched": fetched, "universe_size": len(symbols), "cells": out}, f)
    print(f"shard {idx}: fetched {fetched}/{len(symbols)}; " + ", ".join(f"{len(t)}" for t in out.values()))


if __name__ == "__main__":
    {"shard": run_shard, "aggregate": fr.run_aggregate}[sys.argv[1]]()
