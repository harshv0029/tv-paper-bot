"""B-1110: glitch-bar cleaning in the pl1d + sector replays, and the sector sweep signal_close entry model."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import bar_hygiene as bh  # noqa: E402
import class_a_replay as R  # noqa: E402
import main  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frame(n=60):
    c = np.full(n, 100.0)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6})


def test_clean_bars_drops_bad_open_print_and_jump_and_counts():
    f = _frame()
    f.loc[10, "Open"] = 1000.0  # open far outside the bar's range (the +900% trade bug)
    f.loc[30, "Close"] = 200.0  # >35% jump and close outside the range
    f.loc[30, "High"] = 201.0
    out, dropped = bh.clean_frames({"X": f})
    assert dropped >= 2 and len(out["X"]) == len(f) - dropped
    assert (out["X"]["Open"] < 500).all() and out["X"].index.tolist() == list(range(len(out["X"])))


def test_clean_bars_leaves_clean_frame_untouched():
    out, dropped = bh.clean_frames({"X": _frame()})
    assert dropped == 0 and len(out["X"]) == 60


@pytest.mark.parametrize("p", ["pl1d_main_replay.py", "pl1d_short_main_replay.py"])
def test_pl1d_drivers_clean_frames_and_report_drop(p):
    src = open(os.path.join(REPO, "scripts", p)).read()
    assert "bh.clean_frames(base.load_frames" in src and "bars_dropped_glitch" in src


def test_signal_close_entry_has_own_tags_never_pooled():
    a = R.sweep_cells("1d", [3], [1], ["2d5"], [5])
    b = R.sweep_cells("1d", [3], [1], ["2d5"], [5], entry="signal_close")
    assert {c["tag"] for c in a}.isdisjoint({c["tag"] for c in b})
    assert all(c["tag"].endswith("_ec1__v1") for c in b)
    with pytest.raises(ValueError):
        R.sweep_cells("1d", [3], [1], ["2d5"], [5], entry="bogus")


def test_signal_close_sweep_runs_and_fills_differ(monkeypatch):
    frames = {f"S{k}": R.synthetic_frame(k, 400) for k in range(12)}
    monkeypatch.setattr(main, "_sector_map_cache", {s: ("A" if i < 6 else "B") for i, s in enumerate(frames)})
    res = R.run_sector_sweep(main, frames, R.sweep_cells("1d", [3], [3], ["2d5"], [5], entry="signal_close"), "1d")
    assert res["entry_model"] == "signal_close"
    base = R.run_sector_sweep(main, frames, R.sweep_cells("1d", [3], [3], ["2d5"], [5]), "1d")
    t = "sector_rotation__fade__short__1d__atr2d5_h5_l3_n3"
    a, b = res["cells"][t + "_ec1__v1"], base["cells"][t + "__v1"]
    assert a["n_signals"] == b["n_signals"]
    assert a["by_stop_fill"]["stop"] != b["by_stop_fill"]["stop"]


def test_workflow_passes_entry_input():
    import yaml
    d = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "sector-rotation-sweep.yml")))
    on = d.get("on") or d.get(True)
    assert on["workflow_dispatch"]["inputs"]["entry"]["default"] == "next_open"
    env = [s for s in d["jobs"]["sweep"]["steps"] if s.get("name") == "Sweep"][0]["env"]
    assert "inputs.entry" in env["ENTRY"]
