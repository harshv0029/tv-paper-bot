"""Full-universe replay for the `snd_zone` family (backlog B-33): demand_retest
(long) and supply_retest (short). Calls the REAL main.snd_zone_scan; bookkeeping,
costs and sizing are shared with scripts/fvg3c_replay.py (same cost model).
Modes: shard | aggregate. Env: SHARD_INDEX, SHARD_COUNT, INTERVAL, PERIOD, GRID.
One result row per strategy tag: snd_zone__<variant>__<dir>__<tf>__<params>__v1.
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

ABBR = {"base_candles": "bc", "base_body_atr": "bb", "explosive_body_atr": "ex", "confirm_bars": "cf",
        "max_retests": "rt", "max_zone_age_bars": "za", "entry": "en", "stop_pad_atr": "sp", "rr": "rr",
        "max_hold_bars": "mh", "atr_period": "ap"}
VARIANT_DIR = (("demand_retest", "long"), ("supply_retest", "short"))


def cell_tag(variant, tf, params):
    full = dict(m.SND_DEFAULT_PARAMS); full.update(params)
    direction = dict(VARIANT_DIR)[variant]
    ps = "_".join(f"{ABBR[k]}{fr._fmt(full[k])}" for k in sorted(full))
    return f"snd_zone__{variant}__{direction}__{tf}__{ps}__v1"


def run_shard():
    idx, count = int(os.environ["SHARD_INDEX"]), int(os.environ["SHARD_COUNT"])
    interval, period = os.environ.get("INTERVAL", "5m"), os.environ.get("PERIOD", "60d")
    grid = json.loads(os.environ.get("GRID", "[{}]"))
    cells = [(v, d, g) for g in grid for v, d in VARIANT_DIR]
    symbols = sorted(set(m._load_nse_universe_from_file()))[idx::count]
    print(f"--- shard {idx}/{count}: {len(symbols)} symbols, {len(cells)} cells, {interval}/{period} ---")
    out = {cell_tag(v, interval, g): [] for v, d, g in cells}
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
                scanner = lambda frame, prm, sess, _d=d: m.snd_zone_scan(frame, _d, prm, sessions=sess)  # noqa: E731
                out[cell_tag(v, interval, g)].extend(
                    fr.replay_cell(sym, df, v, d, g, sessions, mins, ts_arr, scanner=scanner, defaults=m.SND_DEFAULT_PARAMS))
            except Exception as e:
                print(f"ERROR {sym} {v}: {e}")
    with open("shard_result.json", "w") as f:
        json.dump({"shard": idx, "fetched": fetched, "universe_size": len(symbols), "cells": out}, f)
    print(f"shard {idx}: fetched {fetched}/{len(symbols)}; " + ", ".join(f"{len(t)}" for t in out.values()))


if __name__ == "__main__":
    {"shard": run_shard, "aggregate": fr.run_aggregate}[sys.argv[1]]()
