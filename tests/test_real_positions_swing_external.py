"""Tests for the Upstash Redis durability mirror for real_positions_swing
(2026-10-05, live NYKAA.NS finding: the dashboard showed this position's
strategy flip from "gap_and_go" (swing) in the morning to "universal-score"
(intraday) later the same day, with no resting stop-loss either time).
Root cause: real_positions_swing was built 2026-09-22, AFTER the 2026-09-08
Upstash durability fix already existed for real_positions (and the
2026-09-30 fix for real_positions_short), and was never added to it - so a
Render restart silently wiped NYKAA's own real_positions_swing row, and the
next reconcile (with no way left to tell this was a swing position) adopted
it into the WRONG table with no strategy at all. Direct mirror of
test_real_positions_short_external.py, same pure-logic + mocked-HTTP style,
no real Upstash account involved.

Also covers the new swing governance-backfill block in
_reconcile_real_positions_core - the swing engine's OWN retry
(_maybe_sync_real_swing_stop_loss) only ran once per IST day with no
escalation; this gives it the same every-5-minute synchronous retry the
long/short engines already had.

Run: pytest tests/test_real_positions_swing_external.py -v
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


def _insert_real_position_swing(conn, symbol="NYKAA.NS", **overrides):
    row = {
        "symbol": symbol, "kotak_trading_symbol": "NYKAA-EQ", "qty": 1,
        "entry_price": 340.10, "entry_order_id": "261005000174189", "opened_at": 1791183000.0,
        "day": "2026-10-05", "stop_loss": 333.30, "sl_order_id": None, "sl_trigger_price": None,
        "strategy": "gap_and_go",
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["symbol"], row["kotak_trading_symbol"], row["qty"], row["entry_price"],
         row["entry_order_id"], row["opened_at"], row["day"], row["stop_loss"],
         row["sl_order_id"], row["sl_trigger_price"], row["strategy"]),
    )
    conn.commit()


def test_sync_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
        with patch("main.requests.post") as mock_post:
            main._sync_real_positions_swing_external(conn)
            mock_post.assert_not_called()


def test_sync_pushes_full_table_snapshot_to_a_separate_redis_key():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_swing(conn, sl_order_id="261005000174405", sl_trigger_price=333.30,
                                         strategy="gap_and_go")
            with patch("main.requests.post") as mock_post:
                main._sync_real_positions_swing_external(conn)
                mock_post.assert_called_once()
                call = mock_post.call_args
                # A SEPARATE key from real_positions'/real_positions_short's
                # own - the three tables' snapshots must never collide.
                assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:real_positions_swing:v1"
                assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
                payload = json.loads(call.kwargs["data"])
                assert len(payload["rows"]) == 1
                assert payload["rows"][0]["symbol"] == "NYKAA.NS"
                assert payload["rows"][0]["sl_order_id"] == "261005000174405"
                assert payload["rows"][0]["strategy"] == "gap_and_go"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_swing(conn)
            with patch("main.requests.post", side_effect=Exception("connection refused")):
                main._sync_real_positions_swing_external(conn)  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_restores_missing_row_from_upstash():
    # The exact live scenario: a restart wiped real_positions_swing, but
    # Upstash still has the last-synced snapshot with the true strategy.
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        saved = {
            "synced_at": 1791183100.0,
            "rows": [{
                "symbol": "NYKAA.NS", "kotak_trading_symbol": "NYKAA-EQ", "qty": 1,
                "entry_price": 340.10, "entry_order_id": "261005000174189", "opened_at": 1791183000.0,
                "day": "2026-10-05", "stop_loss": 333.30, "sl_order_id": "261005000174405",
                "sl_trigger_price": 333.30, "strategy": "gap_and_go",
            }],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_swing_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", ("NYKAA.NS",)).fetchone()
            assert row is not None
            assert row["sl_order_id"] == "261005000174405"
            assert row["strategy"] == "gap_and_go"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_never_overwrites_a_row_already_present():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_swing(conn, symbol="NYKAA.NS", qty=99, sl_order_id="LOCAL_WINS")

        saved = {"rows": [{
            "symbol": "NYKAA.NS", "kotak_trading_symbol": "NYKAA-EQ", "qty": 1,
            "entry_price": 340.10, "entry_order_id": "OLD", "opened_at": 1791183000.0,
            "day": "2026-10-05", "stop_loss": 333.30, "sl_order_id": "STALE",
            "sl_trigger_price": None, "strategy": None,
        }]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json.dumps(saved)}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            main.hydrate_real_positions_swing_from_external()

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", ("NYKAA.NS",)).fetchone()
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
        result = main.hydrate_real_positions_swing_from_external()
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
            result = main.hydrate_real_positions_swing_from_external()
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
            result = main.hydrate_real_positions_swing_from_external()  # must not raise
            assert result is False
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


# ---- Wiring: mutation call sites actually invoke the sync ------------------

def test_swing_exit_syncs_to_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            _insert_real_position_swing(conn, symbol="NYKAA.NS")
            fake_kotak_real_orders = MagicMock()
            fake_kotak_real_orders.place_real_exit.return_value = {
                "ok": True, "order_id": "9", "qty": 1, "fill_price": 339.55, "fill_price_confirmed": True,
            }
            with patch("main._kotak_symbol_still_open", return_value=True), \
                 patch.object(main, "_sync_real_positions_swing_external") as mock_sync, \
                 patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
                main._maybe_place_real_swing_exit(conn, "NYKAA.NS")
        assert mock_sync.called
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


# ---- Swing governance-backfill: the 5-minute auto-heal gap this closes -----

def test_reconcile_backfills_missing_swing_sl_every_call_not_just_once_a_day():
    # The exact standing-rule gap this closes: a swing position missing its
    # resting SL used to only get retried once per IST day (the swing
    # scan's own _maybe_sync_real_swing_stop_loss) - now it's retried every
    # single _reconcile_real_positions_core call, same cadence as long/short.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn, symbol="NYKAA.NS", sl_order_id=None, sl_trigger_price=None)

    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "NYKAA-EQ", "flBuyQty": "1", "flSellQty": "0", "buyAmt": "340.10"},
    ]}
    fake_kotak_real_orders = MagicMock()
    fake_kotak_real_orders.place_real_stop_loss.return_value = {
        "ok": True, "order_id": "SL1", "trigger_price": 333.30,
    }
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
        result = main._reconcile_real_positions_core(adopt=None)

    assert result["governance_backfilled_swing_count"] == 1
    assert result["governance_backfilled_swing"][0]["sl_placed"] is True
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", ("NYKAA.NS",)).fetchone()
        assert row["sl_order_id"] == "SL1"


def test_reconcile_swing_backfill_skips_rows_that_already_have_a_resting_sl():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn, symbol="NYKAA.NS", sl_order_id="ALREADY", sl_trigger_price=333.30)

    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "NYKAA-EQ", "flBuyQty": "1", "flSellQty": "0", "buyAmt": "340.10"},
    ]}
    fake_kotak_real_orders = MagicMock()
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
        result = main._reconcile_real_positions_core(adopt=None)

    assert result["governance_backfilled_swing_count"] == 0
    fake_kotak_real_orders.place_real_stop_loss.assert_not_called()


def test_reconcile_excludes_swing_trading_symbols_from_untracked_detection():
    # Pre-existing 2026-09-30 protection (confirmed still intact after this
    # change): a genuinely-tracked swing position must never show up as
    # "untracked" just because real_positions (intraday)/real_positions_short
    # don't know about it.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn, symbol="NYKAA.NS", sl_order_id="ALREADY", sl_trigger_price=333.30)

    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "NYKAA-EQ", "flBuyQty": "1", "flSellQty": "0", "buyAmt": "340.10"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}):
        result = main._reconcile_real_positions_core(adopt=None)

    assert result["untracked_open_positions_count"] == 0
