"""B-1396a: chan_shape main.py replay merge prints ONE `RESULTS_JSON:` log line in the schema
main._replay_verified_tags() reads (docs/backtest_data/*main_replay_run_*.json). Offline, no network."""
import importlib.util
import json
import pathlib
import sys

import yaml

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import main as app  # noqa: E402
import brk20_replay as br  # noqa: E402

spec = importlib.util.spec_from_file_location("chan_shape_macddiv_main_replay", R / "scripts" / "chan_shape_macddiv_main_replay.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def _tr(net, held, reason):
    return {"gross": net + 0.008, "net": net, "held": held, "reason": reason, "entry_i": 0, "exit_i": held}


def _shard(tmp, shard, trades_by_tag):
    cells = {}
    for t in app.CHAN_SHAPE_CELLS:
        a = br.agg_new()
        br.agg_add(a, trades_by_tag.get(t, []))
        cells[t] = {"raw": a}
    doc = {"family": "chan_shape", "interval": "1d", "period": "5y", "shard": shard, "nshards": 2, "n_symbols": 10,
           "cost_round_trip_pct": app.ROUND_TRIP_COST_PCT, "synthetic": False, "direction": "long",
           "short_mirror": "owed", "cells": cells}
    (tmp / f"chan_shape_s{shard}.json").write_text(json.dumps(doc))


def test_merge_prints_one_results_json_line_in_replay_schema(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    tags = list(app.CHAN_SHAPE_CELLS)
    _shard(tmp_path, 0, {tags[0]: [_tr(0.05, 10, "chan_shape_max_hold_timeout"), _tr(-0.02, 3, "chan_shape_stop_loss")]})
    _shard(tmp_path, 1, {tags[0]: [_tr(0.01, 10, "chan_shape_max_hold_timeout")]})
    cr.merge(str(tmp_path), str(tmp_path / "all.json"))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("RESULTS_JSON: ")]
    assert len(lines) == 1
    doc = json.loads(lines[0][len("RESULTS_JSON: "):])
    assert doc["run_id"] == 123456 and "chan_shape_long_entry_signal" in doc["source"]
    assert doc["family"] == "chan_shape" and doc["cost_round_trip_pct"] == app.ROUND_TRIP_COST_PCT
    assert {r["tag"] for r in doc["rows"]} == set(app.CHAN_SHAPE_CELLS)  # exactly the 6 tags
    r0 = next(r for r in doc["rows"] if r["tag"] == tags[0])
    m = r0["metrics"]
    assert m["n"] == 3 and r0["shards"] == 2 and r0["n_symbols"] == 20
    assert abs(m["pfnet"] - 0.06 / 0.02) < 1e-9 and m["pfgross"] is not None
    assert m["win_pct"] == round(100 * 2 / 3, 2)
    assert m["avg_held_days"] == round(23 / 3, 2) == m["avg_held_bars"]  # 1d bars: held days == held bars
    assert set(m["exit_reasons"]) == {"chan_shape_max_hold_timeout", "chan_shape_stop_loss"}
    empty = next(r for r in doc["rows"] if r["tag"] == tags[1])["metrics"]
    assert empty["n"] == 0 and empty["pfnet"] is None
    assert len(lines[0]) < 8000  # fits a log line
    # what main._replay_verified_tags() applies to each row
    assert all("tag" in r and "n" in r["metrics"] and "pfnet" in r["metrics"] for r in doc["rows"])


def test_run_id_null_offline(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert cr.results_doc({"family": "chan_shape", "rows": []})["run_id"] is None


def test_workflow_merge_step_runs_the_merge_that_prints_results_json():
    wf = yaml.safe_load((R / ".github" / "workflows" / "chan-shape-main-replay.yml").read_text())
    runs = " ".join(s.get("run", "") for s in wf["jobs"]["merge"]["steps"])
    assert "chan_shape_macddiv_main_replay.py merge" in runs
    rep = " ".join(str(s.get("env", "")) + s.get("run", "") for s in wf["jobs"]["replay"]["steps"])
    assert "chan_shape" in rep and "NSHARDS" in rep


def test_replay_calls_the_live_main_functions(monkeypatch):
    calls = {"entry": 0, "exit": 0}
    real_e, real_x = app.chan_shape_long_entry_signal, app.chan_shape_exit_reason

    def e(df, tag):
        calls["entry"] += 1
        return real_e(df, tag)

    def x(*a, **k):
        calls["exit"] += 1
        return real_x(*a, **k)

    monkeypatch.setattr(app, "chan_shape_long_entry_signal", e)
    monkeypatch.setattr(app, "chan_shape_exit_reason", x)
    df = cr.synthetic_frame(1, n=260)
    out = cr.replay_symbol(app, df, "chan_shape", list(app.CHAN_SHAPE_CELLS)[:1], app.ROUND_TRIP_COST_PCT / 100)
    assert calls["entry"] > 0
    if any(out.values()):
        assert calls["exit"] > 0
