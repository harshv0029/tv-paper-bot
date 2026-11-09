"""B-1455: brk20_replay.merge() records the fetch period per interval, never the last shard's value for every row."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brk20_replay as br  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data",
                    "brk20_run_38185670883.json")


def _shard(d, interval, period):
    t = f"brk20_min_rr__main_replay__long__{interval}__atr4_rr4__v1"
    json.dump({"interval": interval, "direction": "long", "period": period, "n_symbols": 1, "cost_round_trip_pct": 0.8,
               "cells": {t: {"cell": {}, "raw": br.agg_new()}}},
              open(os.path.join(d, f"brk20_{interval}_long_s0.json"), "w"))


def test_merge_keeps_period_per_interval(tmp_path):
    _shard(tmp_path, "1d", "5y")
    _shard(tmp_path, "1h", "730d")
    out = br.merge(str(tmp_path))
    assert out["period_by_interval"] == {"1d": "5y", "1h": "730d"}
    assert out["period"].startswith("per interval")
    assert {r["interval"]: r["period"] for r in out["rows"]} == {"1d": "5y", "1h": "730d"}


def test_run_38185670883_label_fixed():
    d = json.load(open(DATA))
    assert d["period_by_interval"] == {"1d": "5y", "1h": "730d", "15m": "60d"}
    assert all(r["period"] == d["period_by_interval"][r["interval"]] for r in d["rows"])
