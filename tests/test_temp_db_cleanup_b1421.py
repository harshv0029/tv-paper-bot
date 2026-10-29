"""B-1421: event-based cleanup of test temp DBs (session end + low-disk sweep at suite start)."""
import importlib.util
import os
import tempfile
import time
from collections import namedtuple
from unittest.mock import patch

import sys

_spec = importlib.util.spec_from_file_location(
    "rtp", os.path.join(os.path.dirname(__file__), "..", "scripts", "run_tests_parallel.py"))
rtp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtp)
conftest = next(m for n, m in list(sys.modules.items()) if n.endswith("conftest") and hasattr(m, "_B1421_CREATED"))
_DU = namedtuple("du", "total used free")


def test_mkstemp_db_is_recorded_and_removed_at_session_end():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    fd2, other = tempfile.mkstemp(suffix=".txt")
    os.close(fd2)
    assert p in conftest._B1421_CREATED and other not in conftest._B1421_CREATED
    saved = set(conftest._B1421_CREATED)
    conftest._B1421_CREATED.intersection_update({p})
    conftest.pytest_sessionfinish(None, 0)
    assert not os.path.exists(p) and os.path.exists(other)
    conftest._B1421_CREATED.update(saved - {p})
    os.remove(other)


def test_low_disk_sweep_removes_only_old_tmp_dbs(tmp_path):
    old, new, keep = tmp_path / "tmpold.db", tmp_path / "tmpnew.db", tmp_path / "data.db"
    for f in (old, new, keep):
        f.write_bytes(b"x")
    past = time.time() - 3 * 3600
    os.utime(old, (past, past))
    os.utime(keep, (past, past))
    with patch.object(rtp.shutil, "disk_usage", return_value=_DU(10, 9, 1e9)):
        assert rtp._sweep_stale_temp_dbs(str(tmp_path)) == 1
    assert not old.exists() and new.exists() and keep.exists()


def test_no_sweep_when_disk_is_healthy(tmp_path):
    f = tmp_path / "tmpold.db"
    f.write_bytes(b"x")
    os.utime(f, (0, 0))
    with patch.object(rtp.shutil, "disk_usage", return_value=_DU(100e9, 10e9, 90e9)):
        assert rtp._sweep_stale_temp_dbs(str(tmp_path)) == 0
    assert f.exists()
