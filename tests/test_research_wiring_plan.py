import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import research_wiring_plan as W  # noqa: E402
import strategy_registry as sr  # noqa: E402


def test_wired_names_parsed_from_main():
    txt = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
    assert "gap_and_go__swing__long__1d__hold30__v1" in W.wired_registry_names(txt)


def test_plan_excludes_control_and_is_sorted():
    rows, ex = W.build(sr.REGISTRY, set())
    assert all("avg1" not in r[1] and "atrnone" not in r[1] for r in rows)
    assert [r[0] for r in rows] == sorted((r[0] for r in rows), reverse=True)
    assert all(r[4] >= W.MIN_N and r[5] <= W.MAX_HOLD_DAYS + 1e-9 for r in rows)
    assert "Candidates" in W.render(rows, ex)
