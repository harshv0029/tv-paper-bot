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


def test_other_append_only_logs_merge_too(remote):  # noqa: F811
    """B-1549 follow-up: trades / real_fo_trades / news_signal_events written before the restore are merged."""
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO trades (ts, symbol, action, qty, price) VALUES (1.0, 'A.NS', 'buy', 1, 10)")
        c.execute("INSERT INTO real_fo_trades (ts, day, leg_key, side, status) VALUES (1.0, '2026-11-14', 'L1', 'B', 'confirmed')")
        c.execute("INSERT INTO news_signal_events (ts, day, symbol, direction, kind, category, action) "
                  "VALUES (1.0, '2026-11-14', 'A.NS', 'long', 'entry', 'x', 'allow')")
        c.commit()
    main.sync_generic_tables_external()
    _fresh_db()
    main._generic_mirror_hydrated.clear()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO trades (ts, symbol, action, qty, price) VALUES (2.0, 'B.NS', 'buy', 1, 20)")
        c.execute("INSERT INTO real_fo_trades (ts, day, leg_key, side, status) VALUES (2.0, '2026-11-14', 'L2', 'B', 'failed')")
        c.execute("INSERT INTO news_signal_events (ts, day, symbol, direction, kind, category, action) "
                  "VALUES (2.0, '2026-11-14', 'B.NS', 'short', 'entry', 'x', 'avoid')")
        c.commit()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        for t in ("trades", "real_fo_trades", "news_signal_events"):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 2, t


def _ledger(c, day, sym, source, bq):
    c.execute("INSERT OR REPLACE INTO kotak_fill_ledger (day, trdsym, prod, source, buy_qty, buy_amt) "
              "VALUES (?, ?, 'CNC', ?, ?, ?)", (day, sym, source, bq, bq * 100))
    c.commit()


def test_kotak_fill_ledger_capture_before_restore_keeps_history(remote):  # noqa: F811
    """B-1564 root cause: a capture before the boot restore must not replace the remote ledger history, and the
    pre-restore 'opening' rows (it wrongly thinks it is the first ever capture) are dropped when a history exists."""
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        _ledger(c, "2026-11-02", "SAIL-EQ", "kotak_positions", 5)
        _ledger(c, "2026-11-04", "RECLTD-EQ", "kotak_positions", 1)
    main.sync_generic_tables_external(only=("kotak_fill_ledger",))  # slow table: bypass the 300 s push interval
    _fresh_db()
    main._generic_mirror_hydrated.clear()
    with closing(main.get_db()) as c:                 # capture runs first after the restart
        _ledger(c, "2026-11-02", "SAIL-EQ", "opening", 5)
        _ledger(c, "2026-11-11", "BANKBARODA-EQ", "kotak_positions", 2)
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        got = sorted((r["day"], r["trdsym"], r["source"]) for r in c.execute("SELECT * FROM kotak_fill_ledger"))
    assert got == [("2026-11-02", "SAIL-EQ", "kotak_positions"), ("2026-11-04", "RECLTD-EQ", "kotak_positions"),
                   ("2026-11-11", "BANKBARODA-EQ", "kotak_positions")]
