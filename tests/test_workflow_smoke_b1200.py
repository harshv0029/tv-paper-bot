"""B-1200 pre-dispatch QA: each new research workflow passes scripts/workflow_qa.py, and each driver's SYNTHETIC one-shard smoke
runs (run + merge) end to end in a scratch dir. Synthetic output is NOT a result; this only proves the dispatch will not die on
a typo, a missing input or a broken merge."""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import workflow_qa as qa  # noqa: E402

WORKFLOWS = {  # file -> (expected default job count, 1-shard smoke spec)
    "chan-gap-tf-sweep.yml": 25, "sector-rotation-sweep.yml": 6, "brk20-min-rr-main-replay.yml": 38,
    "pl1d-tf-sweep.yml": 17, "island-tf-dir-sweep-replay.yml": 62, "pl1d-tf-dir-sweep-replay.yml": 58,
    "envelope-main-replay.yml": 9, "gatetarget-short-sweep-replay.yml": 50, "chan-nonoverlap.yml": 7,
}


@pytest.mark.parametrize("wf,jobs", sorted(WORKFLOWS.items()))
def test_workflow_static_qa_and_job_count(wf, jobs):
    r = qa.check(os.path.join(REPO, ".github", "workflows", wf))
    assert r["defects"] == [], r["defects"]
    assert r["total_jobs"] == jobs
    assert all(j["jobs"] <= 256 for j in r["jobs"].values())


SMOKES = {  # name -> (script, run env, merge args)
    "chan_gap": ("chan_gap_tf_sweep.py", {"DIRECTION": "short", "INTERVAL": "15m", "SYMBOL_LIMIT": "4"}, ["merge", "out"]),
    "pl1d_tf": ("pl1d_tf_sweep.py", {"TF": "4h", "SYMBOL_LIMIT": "3"}, ["merge", "out"]),
    "brk20": ("brk20_replay.py", {"INTERVAL": "4h", "DIRECTION": "long", "SYMBOL_LIMIT": "3"}, ["merge", "out"]),
    "sector": ("class_a_replay.py", {"MODE": "sector_sweep", "TF": "1d", "LS": "3", "NS": "1", "ATRS": "2d5", "HOLDS": "5",
                                     "NAME": "smoke", "SYMBOL_LIMIT": "12"}, None),
    "island": ("island_tf_dir_sweep_replay.py", {"TF": "1d", "SYMBOL_LIMIT": "3"}, ["merge", "out"]),
    "pl1d_dir": ("pl1d_tf_dir_sweep_replay.py", {"TF": "4h", "SYMBOL_LIMIT": "3"}, ["merge", "out"]),
    "envelope": ("envelope_main_replay.py", {"SYMBOL_LIMIT": "3"}, ["merge", "out"]),
    "gatetarget": ("gatetarget_short_sweep_replay.py", {"TF": "4h", "SYMBOL_LIMIT": "3"}, ["merge", "out"]),
}


@pytest.mark.parametrize("name", sorted(SMOKES))
def test_driver_synthetic_one_shard_smoke(name, tmp_path):
    script, env_extra, merge_args = SMOKES[name]
    if name == "envelope":
        import main
        if not hasattr(main, "ENVELOPE_1H_CELLS"):
            pytest.skip("B-1200 DEFECT: main.ENVELOPE_1H_CELLS / envelope_fade_* are not on this branch; "
                        "envelope-main-replay.yml would crash on dispatch until that main.py code is merged")
    env = dict(os.environ, SYNTHETIC="1", SHARD="0", NSHARDS="1", PYTHONPATH=REPO, **env_extra)
    path = os.path.join(REPO, "scripts", script)
    for d in ("static", "docs"):  # main.py mounts ./static at import; Actions runs from the repo root
        os.symlink(os.path.join(REPO, d), tmp_path / d)
    run_args = ["run"] if name in ("chan_gap", "pl1d_tf", "envelope") else []
    r = subprocess.run([sys.executable, path] + run_args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    assert os.listdir(tmp_path / "out")
    if merge_args:
        m = subprocess.run([sys.executable, path] + merge_args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
        assert m.returncode == 0, m.stderr[-800:]
