"""B-1396c: tasuki + swingminrr short main.py replay. Run 38451258979 ran no shards: plan crashed on a top-level pandas
import (plan job installs nothing), wrote an empty matrix, and merge then died on a missing out/ dir. Offline checks."""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.abspath(os.path.join(ROOT, "scripts", "tasuki_swingminrr_short_main_replay.py"))
WF = os.path.join(ROOT, ".github", "workflows", "tasuki-swingminrr-short-main-replay.yml")


def _mod():
    spec = importlib.util.spec_from_file_location("tsm_replay_b1396c", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plan_runs_without_pandas_or_numpy(tmp_path):
    # Block numpy/pandas the way the bare plan runner lacks them; plan must still print a valid matrix.
    stub = tmp_path / "stub"
    stub.mkdir()
    for name in ("pandas", "numpy"):
        (stub / f"{name}.py").write_text("raise ImportError('not installed on the plan runner')\n")
    env = {**os.environ, "PYTHONPATH": str(stub), "NSHARDS": "16"}
    r = subprocess.run([sys.executable, SCRIPT, "plan"], capture_output=True, text=True, env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    inc = json.loads(r.stdout)["include"]
    assert inc[0] == {"group": "tasuki", "shard": 0, "nshards": 1}
    sw = [x for x in inc if x["group"] == "swm1h"]
    assert [x["shard"] for x in sw] == list(range(16)) and all(x["nshards"] == 16 for x in sw)


def test_plan_empty_nshards_defaults_and_rejects_zero():
    mod = _mod()
    assert len(mod.plan({"NSHARDS": ""})["include"]) == 1 + 8
    with pytest.raises(ValueError):
        mod.plan({"NSHARDS": "0"})


def test_merge_zero_shards_fails_loudly_and_creates_dir(tmp_path):
    mod = _mod()
    d = tmp_path / "out"
    with pytest.raises(SystemExit, match="zero shard files"):
        mod.merge(str(d))
    assert d.is_dir() and not (d / "tsm_all.json").exists()


def test_run_and_merge_print_results_json(tmp_path, monkeypatch, capsys):
    import main
    mod = _mod()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("SYMBOL_LIMIT", "2")
    for g in ("tasuki", "swm1h"):
        monkeypatch.setenv("GROUP", g)
        mod.run()
    capsys.readouterr()
    out = mod.merge("out")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("RESULTS_JSON: ")]
    assert len(lines) == 1
    p = json.loads(lines[0][len("RESULTS_JSON: "):])
    assert p["run_id"] is None and p["source"]
    assert {r["tag"] for r in p["rows"]} == set(main.TASUKI_SHORT_CELLS) | set(main.SWINGMINRR_SHORT_1H_CELLS)
    for r in p["rows"]:
        assert {"n", "pfnet", "pfgross", "win_pct", "avg_held_hours", "avg_held_bars", "exit_reasons"} <= set(r["metrics"])
    assert p["cost_round_trip_pct"] == main.ROUND_TRIP_COST_PCT == 0.8
    assert p["rows"] == out["rows"] and os.path.exists("out/tsm_all.json")


def test_universes_and_live_functions(monkeypatch):
    import main
    mod = _mod()
    seen = []
    monkeypatch.delenv("SYNTHETIC", raising=False)
    monkeypatch.setattr(main, "fetch_ohlc", lambda s, p, i: seen.append((s, p, i)) or None)
    monkeypatch.setattr(main, "_load_nse_universe_from_file", lambda: ["A.NS", "B.NS"])
    with pytest.raises(SystemExit):  # nothing loaded -> refuse an all-zero shard
        mod.load_frames(main, "swm1h", 0, 1)
    assert seen == [("A.NS", "730d", "1h"), ("B.NS", "730d", "1h")]
    seen.clear()
    with pytest.raises(SystemExit):
        mod.load_frames(main, "tasuki", 0, 1)
    assert {s for s, _, _ in seen} == set(main.ETF_SYMBOLS) and all(i == "1d" for _, _, i in seen)
    src = open(SCRIPT).read()
    for fn in ("tasuki_short_signal", "tasuki_short_stop", "tasuki_short_exit_reason", "swingminrr_gate_short_entry_signal",
               "swingminrr_gate_short_exit_reason", "_load_nse_universe_from_file", "ROUND_TRIP_COST_PCT"):
        assert f"m.{fn}" in src
    assert "m.NSE_FULL_UNIVERSE" not in src


def test_workflow_validates_plan_and_aggregate_guards():
    wf = open(WF).read()
    assert "set -euo pipefail" in wf and 'assert m["include"]' in wf
    assert "needs: [plan, replay]" in wf and "needs.plan.result == 'success'" in wf
    assert "mkdir -p out" in wf
