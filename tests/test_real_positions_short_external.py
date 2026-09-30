"""Tests for the Upstash Redis durability mirror for real_positions_short
(2026-09-30, explicit user finding: kotak-reconcile.yml successfully
adopted 4 real short positions with real order ids and already-resting
stop-losses recovered from Kotak - and by the very next request seconds
later, all 4 had reverted to "kotak_untracked" again. Root cause:
real_positions_short was built 2026-09-29, AFTER the 2026-09-08 Upstash
durability fix already existed for real_positions, and was never added to
it - so every restart (including the one the SAME reconcile workflow's own
git push triggers, right after the HTTP call returns) silently wiped it
with nothing to survive. Direct mirror of test_real_positions_external.py,
same pure-logic + mocked-HTTP style, no real Upstash account involved.

Run: pytest tests/test_real_positions_short_external.py -v
"""
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


def _insert_real_position_short(conn, symbol="TCS.NS", **overrides):
    row = {
        "symbol": symbol, "kotak_trading_symbol": "TCS-EQ", "qty": 1,
        "entry_price": 2093.9, "entry_order_id": "260930000174189", "opened_at": 1790750000.0,
        "day": "2026-09-30", "sl_order_id": None, "sl_trigger_price": None, "strategy": None,
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["symbol"], row["kotak_trading_symbol"], row["qty"], row["entry_price"],
         row["entry_order_id"], row["opened_at"], row["day"], row["sl_order_id"],
         row["sl_trigger_price"], row["strategy"]),
    )
    conn.commit()


def test_sync_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn)
        with patch("main.requests.post") as mock_post:
            main._sync_real_positions_short_external(conn)
            mock_post.assert_not_called()


def test_sync_pushes_full_table_snapshot_to_a_separate_redis_key():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_short(conn, sl_order_id="260930000174405", sl_trigger_price=2102.8,
                                         strategy="range_short_staged_ladder")
            with patch("main.requests.post") as mock_post:
                main._sync_real_positions_short_external(conn)
                mock_post.assert_called_once()
                call = mock_post.call_args
                # A SEPARATE key from real_positions' own - the two tables'
                # snapshots must never collide or overwrite each other.
                assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:real_positions_short:v1"
                assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
                payload = json.loads(call.kwargs["data"])
                assert len(payload["rows"]) == 1
                assert payload["rows"][0]["symbol"] == "TCS.NS"
                assert payload["rows"][0]["sl_order_id"] == "260930000174405"
                assert payload["rows"][0]["strategy"] == "range_short_staged_ladder"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_short(conn)
            with patch("main.requests.post", side_effect=Exception("connection refused")):
                main._sync_real_positions_short_external(conn)  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_restores_missing_row_from_upstash():
    # The exact live scenario: a restart wiped real_positions_short, but
    # Upstash still has the last-synced snapshot with the real order ids.
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        saved = {
            "synced_at": 1790752600.0,
            "rows": [{
                "symbol": "TCS.NS", "kotak_trading_symbol": "TCS-EQ", "qty": 1,
                "entry_price": 2093.9, "entry_order_id": "260930000174189", "opened_at": 1790750000.0,
                "day": "2026-09-30", "sl_order_id": "260930000174405", "sl_trigger_price": 2102.8,
                "protection_degraded_since": None, "strategy": "range_short_staged_ladder",
            }],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_short_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
            assert row is not None
            assert row["sl_order_id"] == "260930000174405"
            assert row["sl_trigger_price"] == 2102.8
            assert row["strategy"] == "range_short_staged_ladder"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_never_overwrites_a_row_already_present():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_short(conn, symbol="TCS.NS", qty=99, sl_order_id="LOCAL_WINS")

        saved = {"rows": [{
            "symbol": "TCS.NS", "kotak_trading_symbol": "TCS-EQ", "qty": 1,
            "entry_price": 2093.9, "entry_order_id": "OLD", "opened_at": 1790750000.0,
            "day": "2026-09-30", "sl_order_id": "STALE", "sl_trigger_price": None, "strategy": None,
        }]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_short_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
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
        result = main.hydrate_real_positions_short_from_external()
        mock_get.assert_not_called()
        assert result is False


def test_hydrate_returns_true_on_a_successful_empty_read():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": None}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            result = main.hydrate_real_positions_short_from_external()
        assert result is True
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.get", side_effect=Exception("timeout")):
            result = main.hydrate_real_positions_short_from_external()  # must not raise
            assert result is False
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


# ---- Wiring: mutation call sites actually invoke the sync ------------------

def test_short_exit_syncs_to_upstash():
    # Simpler, more direct wiring check than mocking the full entry
    # pipeline: _maybe_place_real_short_exit's DELETE must sync too, so a
    # covered position doesn't get resurrected from a stale Upstash
    # snapshot after the NEXT restart.
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_short(conn, symbol="TCS.NS")
            fake_kotak_real_orders = MagicMock()
            fake_kotak_real_orders.place_real_short_cover.return_value = {
                "ok": True, "order_id": "9", "fill_price": 2070.0,
            }
            with patch.object(main, "_sync_real_positions_short_external") as mock_sync, \
                 patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
                main._maybe_place_real_short_exit(conn, "TCS.NS")
        assert mock_sync.called
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_reconcile_adopt_syncs_short_positions_to_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        fake_positions = {"data": [
            {"exSeg": "nse_cm", "trdSym": "TCS-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "2093.90"},
        ]}
        bot_entry = {
            "actId": "X", "algId": "99999", "ordSrc": "ADMINCPPAPI_NEOTRADEAPI",
            "trdSym": "TCS-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "complete", "nOrdNo": "1",
        }
        with patch("kotak_neo.positions", return_value=fake_positions), \
             patch("kotak_neo.limits", return_value={"Net": "1000"}), \
             patch("kotak_neo.order_report", return_value={"data": [bot_entry]}), \
             patch.object(main, "_sync_real_positions_short_external") as mock_sync:
            result = main._reconcile_real_positions_core(adopt="TCS-EQ")
        assert result["adopted_count"] == 1
        assert mock_sync.called
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
