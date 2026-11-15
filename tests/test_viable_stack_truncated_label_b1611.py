"""B-1611 (live 2026-11-16, View 4 "Real entry needs the definition loaded: NOT loaded"): the restart merge clipped
slot labels to 120 chars, so each restart added a truncated copy of the 13-Nov definition (same created_at) as the
NEWEST row; it parsed to zero slots and VIABLE_STACK_ACTIVE went False (no real entry)."""
import json
import os
import tempfile
from unittest.mock import patch

import main
import strategy_registry as sr

FULL = main.VIABLE_SLOTS_PREFIX + json.dumps(
    [{"name": "Slot 1", "enabled": True, "pf_min": 1.04, "pf_max": 100.0, "min_trades": 1, "max_hold_hrs": 140.0},
     {"name": "Slot 2", "enabled": True, "pf_min": 2.0, "pf_max": 100.0, "min_trades": 1, "max_hold_hrs": 750.0}])
CUT = FULL[:120]
CA = 1794547173.4301581


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _rows():
    with main.closing(main.get_db()) as c:
        return [tuple(r) for r in c.execute("SELECT created_at, label FROM strategy_viable_stack ORDER BY id").fetchall()]


def test_clip_keeps_slot_labels_whole():
    assert len(FULL) > 120
    assert main._stack_label_clip(FULL) == FULL
    assert main._stack_label_clip("x" * 200) == "x" * 120
    assert main._stack_slots(CUT) == []  # the live failure: a cut label parses to zero slots


def test_merge_heals_truncated_copy_and_never_re_adds_it():
    _fresh_db()
    with main.closing(main.get_db()) as c:  # live 16-Nov state: full row then truncated copy on top
        for lab in (FULL, CUT):
            c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)", (CA, lab, "[]"))
        c.commit()
    git_rows = [{"created_at": CA, "label": FULL, "names": []}, {"created_at": CA, "label": CUT, "names": []}]
    with patch.object(main, "_VIABLE_STACK_GIT_RESTORE_IN_TESTS", True), \
            patch.object(main, "_viable_stack_git_rows", return_value=git_rows), \
            patch.object(main, "sync_generic_tables_external"):
        assert main._viable_stack_merge_remote() == 1  # one dropped
        assert main._viable_stack_merge_remote() == 0  # idempotent: the cut copy is not re-added
    rows = _rows()
    assert rows == [(CA, FULL)], rows
    main._VIABLE_OVERRIDES_CACHE.clear()
    main._load_viable_overrides()
    assert sr.VIABLE_STACK_ACTIVE is True


def test_restore_from_remote_keeps_the_full_label():
    _fresh_db()
    with patch.object(main, "_VIABLE_STACK_GIT_RESTORE_IN_TESTS", True), \
            patch.object(main, "_viable_stack_git_rows", return_value=[{"created_at": CA, "label": FULL, "names": []}]):
        assert main._restore_viable_stack_from_git_file() == 1
    assert _rows() == [(CA, FULL)]
    with patch.object(main, "_VIABLE_STACK_GIT_RESTORE_IN_TESTS", True), \
            patch.object(main, "_viable_stack_git_rows", return_value=[{"created_at": CA, "label": FULL, "names": []}]), \
            patch.object(main, "sync_generic_tables_external"):
        assert main._viable_stack_merge_remote() == 0  # full label round-trips: no duplicate
