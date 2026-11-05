"""B-1473: docs/RETEST_SCHEDULE.md must match the registry (regenerate with scripts/retest_due.py)."""
import datetime as dt
import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("retest_due", os.path.join(_ROOT, "scripts", "retest_due.py"))
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


def test_schedule_file_is_fresh():
    assert open(rd.OUT).read() == rd.render(rd.build()), "run: python scripts/retest_due.py"


def test_result_date_parsing():
    assert rd.result_date("run_ref 2026-10-10 IST") == (dt.date(2026, 10, 10), "date")
    assert rd.result_date("oneil-replay (14 Oct 2026, 1w)") == (dt.date(2026, 10, 14), "date")
    assert rd.result_date("diag run 41956627207")[0] == dt.date(2026, 11, 5)
    assert rd.result_date("no evidence") == (rd.RESEARCH_START, "default")
    assert rd.result_date("2026-01-05 typo")[1] == "default"   # before research start is not a result date
