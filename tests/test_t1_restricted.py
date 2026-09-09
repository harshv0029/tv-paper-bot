"""Tests for the T1-holdings avoidance flag (2026-09-08, explicit user
instruction: "if ever such asset is classified as T1 holding then dont
trade in that as they are risk"). See main.py's real_t1_restricted table
comment and _flag_if_t1_restricted/_is_t1_restricted docstrings."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

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


def test_flag_matches_the_real_t2t_same_day_sell_rejection_string():
    # 2026-09-09, MEDICAMEQ.NS - a genuinely different root cause (SEBI/
    # exchange Trade-to-Trade surveillance category, not Kotak's own T1-
    # holdings RMS check) surfacing under a completely different message.
    _fresh_db()
    detail = (
        "order 260909000215155 rejected: Insufficient quantity held for this order. Try "
        "placing an order with a lesser quantity / check open orders in the same scrip / "
        "For MTF stock, select correct product type / Selling Trade-to-Trade stocks on the "
        "same day of purchase is not allowed."
    )
    with closing(main.get_db()) as conn:
        assert main._is_t1_restricted(conn, "MEDICAMEQ.NS") is False
        main._flag_if_t1_restricted(conn, "MEDICAMEQ.NS", detail)
        assert main._is_t1_restricted(conn, "MEDICAMEQ.NS") is True


def test_restriction_is_permanent_not_scoped_to_the_day_it_was_flagged():
    # 2026-09-09, explicit user instruction: "if we can't exit same day
    # then pick strategy accordingly... else dont pick these restricted
    # assets" - a symbol flagged on an EARLIER day must still block entry
    # today, not just on the day it was first discovered (the old
    # day-scoped check would have cheerfully re-entered the same T2T
    # stock every single day with real capital).
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_t1_restricted (symbol, day, flagged_at, detail) VALUES (?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "2020-01-01", 0.0, "stale day, real restriction"),
        )
        conn.commit()
        assert main._is_t1_restricted(conn, "MEDICAMEQ.NS") is True


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


# --- Upstash persistence (2026-09-09) -------------------------------------
# Found live right after making the restriction permanent: real_t1_restricted
# is a plain SQLite table, exactly as ephemeral as everything else on this
# Render service - the very next deploy wiped the flag clean again, defeating
# the "permanent" fix in practice. See main.py's _sync_t1_restricted_external/
# hydrate_t1_restricted_from_external docstrings.

def test_sync_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.requests.post") as mock_post:
            main._sync_t1_restricted_external(conn)
            mock_post.assert_not_called()


def test_flagging_syncs_the_whole_table_to_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            with patch("main.requests.post") as mock_post:
                main._flag_if_t1_restricted(conn, "MEDICAMEQ.NS", "RMS:Rule: Check T1 holdings...")
                mock_post.assert_called_once()
                call = mock_post.call_args
                assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:real_t1_restricted:v1"
                import json as json_mod
                body = json_mod.loads(call.kwargs["data"])
                assert len(body) == 1
                assert body[0]["symbol"] == "MEDICAMEQ.NS"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_restores_rows_and_is_t1_restricted_sees_them():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": json_mod.dumps([
                {"symbol": "MEDICAMEQ.NS", "day": "2026-09-09", "flagged_at": 123.0, "detail": "T2T"},
            ]),
        }
        mock_resp.raise_for_status.return_value = None
        with closing(main.get_db()) as conn:
            with patch("main.requests.get", return_value=mock_resp):
                restored = main.hydrate_t1_restricted_from_external(conn)
            assert restored == 1
            assert main._is_t1_restricted(conn, "MEDICAMEQ.NS") is True
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_0_on_empty_or_failed_read():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            empty_resp = MagicMock()
            empty_resp.json.return_value = {"result": None}
            empty_resp.raise_for_status.return_value = None
            with patch("main.requests.get", return_value=empty_resp):
                assert main.hydrate_t1_restricted_from_external(conn) == 0
            with patch("main.requests.get", side_effect=Exception("timeout")):
                assert main.hydrate_t1_restricted_from_external(conn) == 0  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
