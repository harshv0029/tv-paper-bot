"""B-1580: the short exit path logs a reason (once per symbol per IST day) when no real row exists."""
import os
import tempfile
from contextlib import closing

import main

SYM = "TESTSHORT.NS"


def _setup():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._SHORT_EXIT_NO_ROW_LOGGED.clear()


def test_no_row_logs_reason_once_and_sends_nothing():
    _setup()
    with closing(main.get_db()) as c:
        main._maybe_place_real_short_exit(c, SYM, reason="flatten_1515")
        main._maybe_place_real_short_exit(c, SYM, reason="flatten_1515")
        rows = c.execute("SELECT event, detail FROM real_order_events WHERE symbol = ?", (SYM,)).fetchall()
    assert [r["event"] for r in rows] == ["skipped_no_real_row"]
    assert "flatten_1515" in (rows[0]["detail"] or "")
