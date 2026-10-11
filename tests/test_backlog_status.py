import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import backlog_status as bs  # noqa: E402


def one(row):
    return bs.parse(row)[0][1]


def test_standard_layout():
    assert one("| B-1 | item | DONE | High | n |") == "CLOSED"
    assert one("| B-2 | item | PENDING | P1 | n |") == "OPEN_TODO"
    assert one("| B-3 | item | BLOCKED: data | P1 | n |") == "BLOCKED_OWNER_OR_DATA"
    assert one("| B-4 | item | HARNESS-BUILT-AWAITING-RUN | P1 | n |") == "RUN_PENDING"
    assert one("| B-5 | item | DONE-PENDING-VERIFY (x) | P1 | n |") == "VERIFY_KOTAK"
    assert one("| B-6 | item | CLOSED-AS-EXPLAINED | Medium | n |") == "CLOSED"


def test_shifted_layouts():
    assert one("| B-7 | P2 | DONE | item text | n |") == "CLOSED"
    assert one("| B-8 | DONE | P1 | item text | n |") == "CLOSED"
    assert one("| B-9 | PARTIAL: harness built + n200 run | P1 | x |") == "RUN_PENDING"
    assert one("| B-10 | DONE-PENDING-VERIFY (u) | MERGED (gate) | Medium | n |") == "VERIFY_KOTAK"
    assert one("| B-11 | Merge Box Theory | PARTIAL 2026-10-11 | High | n |") == "OPEN_TODO"


def test_total_equals_row_count():
    text = open(bs.BACKLOG, encoding="utf-8").read()
    n = sum(1 for l in text.splitlines() if l.startswith("| B-"))
    rows = bs.parse(text)
    assert len(rows) == n
    assert all(b in bs.BUCKETS for _, b in rows)
