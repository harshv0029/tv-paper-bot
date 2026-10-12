"""B-812/B-814, B-789/B-815, B-45, B-850/B-852 dispatch readiness: interval/period inputs wired through,
scripts fetch via the capping helper, backlog rows carry exact dispatch commands."""
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = ".git" + "hub"

ROWS = {
    "macddiv-nonoverlap.yml": ("macddiv_nonoverlap.py", True),
    "island-validation.yml": ("island_validation.py", True),
    "intraday-gap-and-go-research.yml": ("intraday_gap_and_go_research.py", True),
    "elder-ge11-validate.yml": ("elder_ge11_validate.py", False),
}


def _read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


def _inputs(wf):
    d = yaml.safe_load(_read(GH, "workflows", wf))
    return d.get("on", d.get(True))["workflow_dispatch"]["inputs"]


@pytest.mark.parametrize("wf", list(ROWS))
def test_workflow_has_interval_and_period_and_passes_them(wf):
    raw = _read(GH, "workflows", wf)
    i = _inputs(wf)
    assert "interval" in i and "period" in i
    assert "--interval" in raw and "--period" in raw


@pytest.mark.parametrize("wf", [w for w, (_, uses) in ROWS.items() if uses])
def test_scripts_fetch_through_capping_helper(wf):
    s = _read("scripts", ROWS[wf][0])
    assert "ri.fetch_interval(" in s
    assert "m.fetch_ohlc(s, " not in s


def test_defaults_unchanged():
    i = _inputs("macddiv-nonoverlap.yml")
    assert i["interval"]["default"] == "1h" and i["period"]["default"] == ""
    i = _inputs("island-validation.yml")
    assert i["interval"]["default"] == "1d" and i["period"]["default"] == "5y"
    i = _inputs("intraday-gap-and-go-research.yml")
    assert i["interval"]["default"] == "5m" and i["period"]["default"] == "60d"


def test_capped_periods_for_these_intervals():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import research_interval as ri
    assert ri.cap_period("1h", "5y") == "730d"
    assert ri.cap_period("15m", "5y") == "60d"
    assert ri.cap_period("5m", "") == "60d"


def test_elder_ge11_resamples_4h():
    s = _read("scripts", "elder_ge11_validate.py")
    assert 'interval == "4h"' in s and "resample_1h_to_4h" in s


def test_backlog_rows_have_dispatch_commands():
    b = _read("docs", "ACTIONABLES_BACKLOG.md")
    assert "DISPATCH-READY 2026-10-12" in b
    for cmd in (
        "gh workflow run macddiv-nonoverlap.yml -f interval=15m",
        "gh workflow run island-validation.yml -f interval=1h",
        "gh workflow run intraday-gap-and-go-research.yml -f interval=5m",
        "gh workflow run elder-ge11-validate.yml -f interval=1h",
    ):
        assert cmd in b, cmd
