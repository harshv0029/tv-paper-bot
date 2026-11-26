"""B-1730: an SL refused because Kotak shows the shares already sold today is logged once as skipped_already_sold."""
import os
import tempfile
from contextlib import closing

import main


def test_already_sold_refusal_is_a_skip_once_per_day():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._sl_after_1515_logged.clear()
    det = "B-1581: Kotak shows MANKIND-EQ already sold/exiting today (start-of-day qty 1)"
    with closing(main.get_db()) as conn:
        for _ in range(3):
            main._log_real_order_event(conn, "MANKIND.NS", "sl", "failed", detail=det)
        main._log_real_order_event(conn, "MANKIND.NS", "sl", "failed", detail="RMS rejected")
        rows = conn.execute("SELECT symbol, event FROM real_order_events ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("MANKIND.NS", "skipped_already_sold"), ("MANKIND.NS", "failed")]
