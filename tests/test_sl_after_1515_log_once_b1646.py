"""B-1646: post-15:15 IST SL refusals are logged once per symbol/leg/day as skipped_after_1515, not as failed."""
import os
import tempfile
from contextlib import closing

import main


def test_logged_once_as_skip_other_failures_untouched():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._sl_after_1515_logged.clear()
    with closing(main.get_db()) as conn:
        for _ in range(3):
            main._log_real_order_event(conn, "TESTSTOCK.NS", "sl", "failed", detail="no SL placement after 15:15 IST")
        main._log_real_order_event(conn, "OTHER.NS", "sl", "failed", detail="no short SL placement after 15:15 IST")
        main._log_real_order_event(conn, "TESTSTOCK.NS", "sl", "failed", detail="RMS rejected")
        rows = conn.execute("SELECT symbol, event FROM real_order_events ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("TESTSTOCK.NS", "skipped_after_1515"), ("OTHER.NS", "skipped_after_1515"),
                                        ("TESTSTOCK.NS", "failed")]
