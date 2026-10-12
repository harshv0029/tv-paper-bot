import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import minervini_sweep_compare as mc


def test_analyse_reads_lab_output_shape():
    doc = {"results": {
        "minervini_vcp__atrtrail__long__1d__atr4_h60__v1": {
            "n": 3845, "pfnet_net": 1.342, "pfnet_gross": 1.6, "win_pct": 40.0, "avg_held_bars": 29.6,
            "exits": {"trail_stop": 60, "max_hold": 40}, "universe_size": 1900},
        "minervini_vcp__atrtrail__long__1d__atr1d5_h60__v1": {
            "n": 3845, "pfnet_net": 0.908, "avg_held_bars": 8.26, "exits": {}}}}
    rows = {r["tag"]: r for r in mc.analyse(doc)}
    a = rows["minervini_vcp__atrtrail__long__1d__atr4_h60__v1"]
    assert a["clears_floor"] and a["exit_share_pct"]["trail_stop"] == 60.0
    assert a["excess_pf_per_held_bar"] == round(0.342 / 29.6, 4)
    assert not rows["minervini_vcp__atrtrail__long__1d__atr1d5_h60__v1"]["clears_floor"]
