"""B-1396b: month_effect_main_replay.py prints ONE `RESULTS_JSON: {...}` line in the layout main._replay_verified_tags()
reads, so the coordinator can save the result from the run log (the artifact is not downloadable). Offline, no network."""
import json
import os
import sys

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brk20_replay as B  # noqa: E402
import month_effect_main_replay as R  # noqa: E402


def _shard(tmp, interval, trades_by_tag):
    cells = {}
    for tag, spec in R.cell_specs(main, interval).items():
        a = B.agg_new()
        B.agg_add(a, trades_by_tag.get(tag, []))
        cells[tag] = {"spec": spec, "raw": a}
    res = {"shard": 0, "nshards": 1, "n_symbols": 3, "interval": interval, "period": R.PERIOD[interval],
           "cost_round_trip_pct": main.ROUND_TRIP_COST_PCT, "synthetic": False, "note": "t", "cells": cells}
    with open(os.path.join(tmp, f"month_effect_{interval}_s0.json"), "w") as f:
        json.dump(res, f)


def _results_line(out):
    lines = [ln for ln in out.splitlines() if ln.startswith("RESULTS_JSON: ")]
    assert len(lines) == 1
    return json.loads(lines[0][len("RESULTS_JSON: "):])


def test_results_json_line_layout_and_fields(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    win = {"gross": 0.05, "net": 0.042, "held": 25, "reason": "max_hold"}
    loss = {"gross": -0.01, "net": -0.018, "held": 3, "reason": "stop"}
    tags15 = list(main.MONTH_EFFECT_SHORT_TAGS)
    _shard(str(tmp_path), "15m", {tags15[0]: [win, win, loss], tags15[1]: [loss]})
    _shard(str(tmp_path), "1d", {})
    R.merge(str(tmp_path))
    d = _results_line(capsys.readouterr().out)
    assert d["run_id"] == 12345 and "month_effect" in d["source"]
    assert d["cost_round_trip_pct"] == main.ROUND_TRIP_COST_PCT == 0.8
    by = {r["tag"]: r for r in d["rows"]}
    # exactly the 4 live 15m tags, plus their 1d re-expressions as their OWN tags (never merged)
    assert set(main.MONTH_EFFECT_SHORT_TAGS) <= set(by)
    assert {t for t in by if "__1d__" in t} and all("__15m__" in t or "__1d__" in t for t in by)
    assert len(by) == 8
    m0 = by[tags15[0]]["metrics"]
    for k in ("n", "pfnet", "pfgross", "win_pct", "avg_held_hours", "avg_held_bars", "exit_reasons"):
        assert k in m0
    assert m0["n"] == 3 and abs(m0["pfnet"] - 0.084 / 0.018) < 1e-9 and m0["win_pct"] == round(200 / 3, 2)
    assert m0["avg_held_hours"] == round((25 + 25 + 3) / 3 * 0.25, 1)
    assert by[tags15[1]]["metrics"]["pfnet"] == 0.0
    assert by[tags15[0]]["interval"] == "15m"


def test_results_json_feeds_replay_verified_tags(tmp_path, monkeypatch):
    """Saved as docs/backtest_data/*main_replay_run_*.json, a row with n>=1 and PFnet>=floor verifies its tag."""
    tags15 = list(main.MONTH_EFFECT_SHORT_TAGS)
    merged = {"cost_round_trip_pct": 0.8, "synthetic": False, "note": "t", "rows": [
        {"tag": tags15[0], "interval": "15m", "spec": {}, "n_symbols": 1, "shards": 1,
         "metrics": {"n": 5, "pfnet": 2.0, "pfgross": 2.5, "win_pct": 60.0, "avg_held_hours": 6.2}},
        {"tag": tags15[1], "interval": "15m", "spec": {}, "n_symbols": 1, "shards": 1,
         "metrics": {"n": 5, "pfnet": 0.5, "pfgross": 0.7, "win_pct": 20.0, "avg_held_hours": 1.0}}]}
    d = R.results_json(merged, None)
    assert d["run_id"] is None
    bd = tmp_path / "docs" / "backtest_data"
    bd.mkdir(parents=True)
    (bd / "month_effect_main_replay_run_test.json").write_text(json.dumps(d))
    real_dirname = os.path.dirname
    monkeypatch.setattr(main.os.path, "dirname",
                        lambda p: str(tmp_path) if p == os.path.abspath(main.__file__) else real_dirname(p))
    ok = main._replay_verified_tags()
    assert tags15[0] in ok and tags15[1] not in ok


def test_results_json_bad_run_id_is_null():
    assert R.results_json({"rows": []}, "abc")["run_id"] is None
