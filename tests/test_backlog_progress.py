import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_backlog_progress_runs_on_real_file(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "backlog_progress", os.path.join(ROOT, "scripts", "backlog_progress.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    before = open(m.SRC, encoding="utf-8").read()
    out = tmp_path / "p.md"
    rows, groups = m.main(str(out))
    n_rows = sum(1 for l in before.splitlines() if l.startswith("| B-"))
    assert len(rows) == n_rows > 100
    assert all(r["prio"] in ("P0", "P1", "P2", "P3", "Info", "P?") for r in rows)
    assert out.read_text().startswith("# Backlog progress")
    assert sum(len(v) for v in groups.values()) == sum(1 for r in rows if not r["closed"])
    assert open(m.SRC, encoding="utf-8").read() == before


def test_b1696_status_after_area_and_item_columns():
    spec = importlib.util.spec_from_file_location(
        "backlog_progress", os.path.join(ROOT, "scripts", "backlog_progress.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    hdr = {"status": 2, "priority": 3}
    r = m.parse_row("| B-9001 | P1 | all | 2026-11-24 IST user: fix the thing | DONE (evidence) |", hdr)
    assert r["prio"] == "P1" and m.norm_status(r["status"]) == "DONE"
    r = m.parse_row("| B-9002 | P2 | options | user asked for paper variants | OPEN (planned) |", hdr)
    assert m.norm_status(r["status"]) == "OPEN"
