import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import shadow_log_report as R  # noqa: E402
import main  # noqa: E402


def _r(tag, taken, hard, sym="A", day="d"):
    return {"strategy_tag": tag, "symbol": sym, "direction": "long", "taken": taken,
            "reason": "x", "hard_gate": hard, "day": day}


def test_report_splits_groups_and_pfnet():
    rows = [_r("t", 1, 0, "A"), _r("t", 0, 1, "B"), _r("t", 0, 0, "C")]
    out = R.build_report(rows, {("t", "A", "d"): 0.04, ("t", "C", "d"): -0.02, ("t", "B", "d"): -0.01})
    r = out[0]
    assert r["taken"]["n"] == 1 and r["hard_skip"]["n"] == 1 and r["discretionary_skips"] == 1
    assert r["taken"]["pfnet"] == float("inf") and r["disc_skip"]["pfnet"] == 0.0


def test_report_without_outcomes():
    assert R.build_report([_r("t", 1, 0)])[0]["taken"]["pfnet"] is None


def test_taken_hooks_present_at_all_three_entry_sites():
    for fn, word in ((main._maybe_place_real_entry, "real long entry placed"),
                     (main._maybe_place_real_short_entry, "real short entry placed"),
                     (main._maybe_place_real_swing_entry, "real swing entry placed")):
        assert word in inspect.getsource(fn), fn.__name__
