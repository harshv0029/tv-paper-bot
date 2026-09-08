"""Tests for the T1-holdings avoidance flag (2026-09-08, explicit user
instruction: "if ever such asset is classified as T1 holding then dont
trade in that as they are risk"). See main.py's real_t1_restricted table
comment and _flag_if_t1_restricted/_is_t1_restricted docstrings."""
import os
import tempfile
from contextlib import closing

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_flag_matches_the_real_kotak_rejection_string():
    _fresh_db()
    detail = ("order 260908000597779 rejected: 16283 : RMS:Rule: Check T1 holdings including "
               "TT/BE/Z/T/TS ,No Holdings Present  for entity account-XUAEZ across exchange "
               "across segment across product ")
    with closing(main.get_db()) as conn:
        assert main._is_t1_restricted(conn, "ADVENTHTL.NS") is False
        main._flag_if_t1_restricted(conn, "ADVENTHTL.NS", detail)
        assert main._is_t1_restricted(conn, "ADVENTHTL.NS") is True
        # a different symbol is unaffected
        assert main._is_t1_restricted(conn, "AARTIIND.NS") is False


def test_flag_ignores_unrelated_rejection_reasons():
    _fresh_db()
    with closing(main.get_db()) as conn:
        main._flag_if_t1_restricted(conn, "XYZ.NS", "order rejected: 16283 : Order price is not a multiple of tick size")
        assert main._is_t1_restricted(conn, "XYZ.NS") is False
        main._flag_if_t1_restricted(conn, "XYZ.NS", None)
        assert main._is_t1_restricted(conn, "XYZ.NS") is False


def test_flag_is_idempotent_and_never_raises():
    _fresh_db()
    detail = "RMS:Rule: Check T1 holdings...No Holdings Present"
    with closing(main.get_db()) as conn:
        main._flag_if_t1_restricted(conn, "AGL.NS", detail)
        main._flag_if_t1_restricted(conn, "AGL.NS", detail)  # must not raise on the second call
        rows = conn.execute("SELECT * FROM real_t1_restricted WHERE symbol = 'AGL.NS'").fetchall()
        assert len(rows) == 1


def test_entry_gate_skips_a_t1_restricted_symbol():
    """_maybe_place_real_entry must refuse a NEW entry for a symbol already
    flagged today, before ever touching the live tick feed or placing an
    order - proven here by NOT stubbing kotak_live_feed/kotak_real_orders
    at all: if the gate didn't return early, the missing 'kotak_live_feed'
    module import would raise instead of a clean early return."""
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
            "VALUES (1, 1, ?, 'test', 'test')", (main.time.time(),),
        )
        conn.commit()
        main._flag_if_t1_restricted(conn, "ADVENTHTL.NS", "RMS:Rule: Check T1 holdings...No Holdings Present")
        os.environ["REAL_TRADING_ENABLED"] = "YES"
        try:
            main._maybe_place_real_entry(conn, "ADVENTHTL.NS")  # must return early, not raise
        finally:
            del os.environ["REAL_TRADING_ENABLED"]
        row = conn.execute(
            "SELECT status FROM real_trades WHERE symbol = 'ADVENTHTL.NS' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["status"] == "skipped_t1_restricted"
