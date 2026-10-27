"""B-1391: swing daily-fetch skips keep the real error, retry once, and clear when a later fetch succeeds."""
import json

from fastapi import HTTPException

import main
from tests.test_swing_skipped_durable import _setup


def test_short_fetch_error_text():
    assert main._short_fetch_error(HTTPException(404, detail="No data for symbol='X.NS'")) == \
        "HTTPException: No data for symbol='X.NS'"
    assert main._short_fetch_error(RuntimeError("Too Many Requests.\n Rate limited")) == \
        "RuntimeError: Too Many Requests. Rate limited"
    assert main._short_fetch_error(ValueError()) == "ValueError"


def test_clear_removes_and_persists(monkeypatch):
    r = _setup(monkeypatch)
    main._note_swing_skipped("AUBANK.NS", "daily fetch failed (RuntimeError: x)")
    main._note_swing_skipped("XYZ.NS", "under 50 daily bars")
    main._clear_swing_skipped("AUBANK.NS")
    main._clear_swing_skipped("NOPE.NS")  # absent: no error
    assert main._swing_skipped_today["syms"] == {"XYZ.NS": "under 50 daily bars"}
    assert json.loads(r.kv[main._SWING_SKIPPED_REDIS_KEY])["syms"] == {"XYZ.NS": "under 50 daily bars"}


def test_scan_source_retries_and_clears():
    src = open("main.py").read()
    a = src.index("def _pf(sym):")
    block = src[a:a + 4000]
    assert "for _attempt in (0, 1):" in block and "SWING_FETCH_RETRY_PAUSE_S" in block
    assert 'f"daily fetch failed ({_short_fetch_error(e)})"' in block
    assert "_clear_swing_skipped(symbol)" in block
