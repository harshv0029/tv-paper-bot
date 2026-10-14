"""B-980 (15m chan_kalman short cells) + B-981 (chan_gap short open-print scan, replay owed)."""
import inspect
import json
import os
import subprocess
import sys

import main
import strategy_registry as sr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "chan_gap_main_replay.py")

T15 = [
    "chan_kalman__band_mr__short__15m__atr4d0_hold40_ve10d0e4_z2d0_fl1515__v2",
    "chan_kalman__band_mr__short__15m__atr2d5_hold40_ve10d0e4_z2d0_fl1515__v2",
    "chan_kalman__band_mr__short__15m__atr1d5_hold40_ve10d0e4_z2d0_fl1515__v2",
]


def test_15m_cells_wired_mapped_verified():
    names = {d.name for d in sr.REGISTRY}
    for t in T15:
        assert t in main.CHAN_SHORT_CELLS and main.CHAN_SHORT_CELL_INTERVAL[t] == "15m"
        assert t in names and main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t not in main.REPLAY_OWED_TAGS  # replay 38390561217 on file
        assert t in main._replay_verified_tags()
    assert len([t for t in main.CHAN_SHORT_CELLS if "__15m__" in t]) == 3
    assert not any("z1d0" in t or "ve1d0e4" in t for t in main.CHAN_SHORT_CELLS if "__15m__" in t)
    assert main.CHAN_SHORT_CELL_INTERVAL[main.CHAN_SHORT_TAG] == "5m"


def test_entry_loop_filters_by_interval_and_manage_uses_cell_interval():
    assert "CHAN_SHORT_CELL_INTERVAL[_t] != interval" in inspect.getsource(main._chan_short_try_entry)
    assert "_chan_short_df_for" in inspect.getsource(main._chan_short_manage)
    for t in T15:
        row = {"stop_loss": 110.0, "entry_price": 100.0, "entry_ts": 0, "strategy": t}
        assert main._chan_short_manage(None, "X", row, None, None, "5m", 600, 111.0, False) == "stop_hit"
        assert main._chan_short_manage(None, "X", row, None, None, "5m", 15 * 60 + 10, 99.0, False) == "flatten_1515"


def test_chan_gap_short_gate_follows_replay_evidence():
    t = main.CHAN_GAP_SHORT_TAG
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
    assert t in main.CHAN_INTRADAY_SHORT_TAGS and t not in main.CHAN_SHORT_CELLS
    # B-1221: run 38502123279 (main.py replay, PFnet 1.31) is on file -> owed flag cleared, gate derives open
    assert t not in main.REPLAY_OWED_TAGS
    assert main._is_strategy_viable_for_real_money(t, check_switch=False)


def test_chan_gap_manage_stop_flatten_only():
    row = {"stop_loss": 110.0, "entry_price": 100.0, "entry_ts": 0, "strategy": main.CHAN_GAP_SHORT_TAG}
    assert main._chan_short_manage(None, "X", row, None, None, "5m", 600, 111.0, False) == "stop_hit"
    assert main._chan_short_manage(None, "X", row, None, None, "5m", 15 * 60 + 10, 99.0, False) == "flatten_1515"
    assert main._chan_short_manage(None, "X", row, None, None, "5m", 700, 99.0, False) is None


def test_real_path_uses_intraday_tag_set():
    assert "CHAN_INTRADAY_SHORT_TAGS" in inspect.getsource(main._chan_short_flatten_due)
    assert "CHAN_INTRADAY_SHORT_TAGS" in inspect.getsource(main._maybe_place_real_short_entry)


def test_replay_script_smoke_and_schema(tmp_path):
    env = {**os.environ, "SYNTHETIC": "1", "SHARD": "0", "NSHARDS": "1", "SYMBOL_LIMIT": "6", "PYTHONPATH": ROOT}
    import shutil
    subprocess.run([sys.executable, SCRIPT, "run"], cwd=ROOT, env=env, check=True, capture_output=True)  # main needs ./static
    shutil.move(os.path.join(ROOT, "out"), str(tmp_path / "out"))
    out = tmp_path / "all.json"
    subprocess.run([sys.executable, SCRIPT, "merge", str(tmp_path / "out"), str(out)], cwd=ROOT, env=env,
                   check=True, capture_output=True)
    row = json.load(open(out))["rows"][0]
    assert row["tag"] == main.CHAN_GAP_SHORT_TAG and "n" in row["metrics"] and "pfnet" in row["metrics"]
