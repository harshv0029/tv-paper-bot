"""B-1549 (2026-11-11): real_trades rows written before the Upstash restore succeeded wiped the remote history on the
next push (ids restarted at 1). The restore now MERGES into a non-empty local real_trades."""
from contextlib import closing

import main
from tests.test_generic_table_mirror import _fresh_db, remote  # noqa: F401 (fixture)


def _attempt(c, ts, sym, status):
    c.execute("INSERT INTO real_trades (ts, day, symbol, side, status, strategy) VALUES (?, '2026-11-11', ?, 'B', ?, 's')",
              (ts, sym, status))
    c.commit()


def test_rows_written_before_restore_are_merged_not_lost(remote):  # noqa: F811
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        _attempt(c, 1.0, "CGPOWER.NS", "confirmed")
        _attempt(c, 2.0, "LENSKART.NS", "skipped_sector_cap")
    assert main.sync_generic_tables_external() >= 1
    _fresh_db()                                   # restart
    main._generic_mirror_hydrated.clear()
    with closing(main.get_db()) as c:             # the scan logs an attempt BEFORE the restore runs
        _attempt(c, 3.0, "UPL.NS", "confirmed")
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        got = [(r["symbol"], r["status"]) for r in c.execute("SELECT symbol, status FROM real_trades ORDER BY ts")]
    assert got == [("CGPOWER.NS", "confirmed"), ("LENSKART.NS", "skipped_sector_cap"), ("UPL.NS", "confirmed")]
    main.sync_generic_tables_external()           # and the next push keeps all three
    _fresh_db()
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert c.execute("SELECT COUNT(*) FROM real_trades").fetchone()[0] == 3


def test_same_row_is_not_duplicated(remote):  # noqa: F811
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        _attempt(c, 1.0, "CGPOWER.NS", "confirmed")
    main.sync_generic_tables_external()
    main._generic_mirror_hydrated.clear()         # local still holds the same row (restore retried)
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert c.execute("SELECT COUNT(*) FROM real_trades").fetchone()[0] == 1
