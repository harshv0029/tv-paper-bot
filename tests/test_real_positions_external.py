"""Tests for the Upstash Redis real-money persistence added 2026-09-08 (see
main.py's "Real-money external persistence" comment block) - real_positions
must survive a Render restart without waiting on the slower git-JSON journal.
Pure logic + a mocked HTTP layer, no real Upstash account or network call
involved - never touches kotak_neo/kotak_real_orders."""
import json
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


def _insert_real_position(conn, symbol="AARTIIND.NS", **overrides):
    row = {
        "symbol": symbol, "kotak_trading_symbol": "AARTIIND-EQ", "qty": 1,
        "entry_price": 502.3, "entry_order_id": "260908000341676", "opened_at": 1788860000.0,
        "day": "2026-09-08", "sl_order_id": None, "sl_trigger_price": None,
        "target_order_id": None, "target_price": None,
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, "
        "target_order_id, target_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["symbol"], row["kotak_trading_symbol"], row["qty"], row["entry_price"],
         row["entry_order_id"], row["opened_at"], row["day"], row["sl_order_id"],
         row["sl_trigger_price"], row["target_order_id"], row["target_price"]),
    )
    conn.commit()


def test_sync_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        with patch("main.requests.post") as mock_post:
            main._sync_real_positions_external(conn)
            mock_post.assert_not_called()


def test_sync_pushes_full_table_snapshot_to_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position(conn, symbol="AARTIIND.NS", sl_order_id="260908000633933",
                                   sl_trigger_price=497.3)
            with patch("main.requests.post") as mock_post:
                main._sync_real_positions_external(conn)
                mock_post.assert_called_once()
                call = mock_post.call_args
                assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:real_positions:v1"
                assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
                payload = json.loads(call.kwargs["data"])
                assert len(payload["rows"]) == 1
                assert payload["rows"][0]["symbol"] == "AARTIIND.NS"
                assert payload["rows"][0]["sl_order_id"] == "260908000633933"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position(conn)
            with patch("main.requests.post", side_effect=Exception("connection refused")):
                main._sync_real_positions_external(conn)  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_restores_missing_row_from_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        saved = {
            "synced_at": 1788860760.0,
            "rows": [{
                "symbol": "AARTIIND.NS", "kotak_trading_symbol": "AARTIIND-EQ", "qty": 1,
                "entry_price": 502.3, "entry_order_id": "260908000341676", "opened_at": 1788860000.0,
                "day": "2026-09-08", "sl_order_id": "260908000633933", "sl_trigger_price": 497.3,
                "target_order_id": None, "target_price": 517.36,
            }],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("AARTIIND.NS",)).fetchone()
            assert row is not None
            assert row["sl_order_id"] == "260908000633933"
            assert row["sl_trigger_price"] == 497.3
            assert row["target_price"] == 517.36
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_never_overwrites_a_row_already_present():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            # Fresh process already has an entry for this symbol (e.g. a
            # scheduler tick raced ahead of startup hydration) - the stale
            # Upstash snapshot must never clobber it.
            _insert_real_position(conn, symbol="AARTIIND.NS", qty=99, sl_order_id="LOCAL_WINS")

        saved = {"rows": [{
            "symbol": "AARTIIND.NS", "kotak_trading_symbol": "AARTIIND-EQ", "qty": 1,
            "entry_price": 502.3, "entry_order_id": "OLD", "opened_at": 1788860000.0,
            "day": "2026-09-08", "sl_order_id": "STALE", "sl_trigger_price": None,
            "target_order_id": None, "target_price": None,
        }]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("AARTIIND.NS",)).fetchone()
            assert row["qty"] == 99
            assert row["sl_order_id"] == "LOCAL_WINS"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with patch("main.requests.get") as mock_get:
        main.hydrate_real_positions_from_external()
        mock_get.assert_not_called()


def test_hydrate_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.get", side_effect=Exception("timeout")):
            main.hydrate_real_positions_from_external()  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
