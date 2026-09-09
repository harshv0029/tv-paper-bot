"""Tests for the missing-signal_state self-heal fix (2026-09-09, explicit
user finding: "the trailing stop loss is not being maintained at the end
of Kotak Neo... if not being done then do that now"). Root cause: a
restart wiped paper signal_state for symbols that still had a genuinely
open real position - _maybe_sync_real_stop_loss's very first real check
(SELECT ... FROM signal_state) returned nothing, so it returned early
EVERY tick, never syncing the trailing stop, and _auto_signal_core's own
position-management branch never even saw these symbols. See main.py's
_ensure_signal_state_for_real_position docstring."""
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


def _insert_real_position(conn, symbol="MEDICAMEQ.NS", entry_price=291.4, qty=3, sl_order_id=None,
                           sl_trigger_price=None):
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol, symbol.replace(".NS", "-EQ"), qty, entry_price, "1", main.time.time(),
         main.ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price),
    )
    conn.commit()


def test_ensure_signal_state_creates_a_row_when_missing():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("MEDICAMEQ.NS",)).fetchone()
        created = main._ensure_signal_state_for_real_position(conn, real_row)
        assert created is True
        row = conn.execute(
            "SELECT * FROM signal_state WHERE symbol = ? AND status = 'long'", ("MEDICAMEQ.NS",)
        ).fetchone()
        assert row is not None
        assert row["entry_price"] == 291.4
        # Uses whatever stop_pct WATCHLIST's own config resolves for this
        # symbol (falls back to 2.0 only if truly absent from WATCHLIST) -
        # same math a fresh entry would have used, not a hardcoded number.
        watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in main.WATCHLIST}
        stop_pct = watchlist_by_symbol.get("MEDICAMEQ.NS", {}).get("stop_pct", 2.0)
        assert row["stop_loss"] == round(291.4 * (1 - stop_pct / 100), 2)


def test_ensure_signal_state_returns_false_and_does_not_overwrite_an_existing_row():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
            "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, 1.0, '5m')",
            ("MEDICAMEQ.NS", main.ist_now().strftime("%Y-%m-%d"), 291.4, 285.0, 285.0, 320.0, 3, main.time.time()),
        )
        conn.commit()
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("MEDICAMEQ.NS",)).fetchone()
        created = main._ensure_signal_state_for_real_position(conn, real_row)
        assert created is False
        row = conn.execute(
            "SELECT * FROM signal_state WHERE symbol = ? AND status = 'long'", ("MEDICAMEQ.NS",)
        ).fetchone()
        assert row["stop_loss"] == 285.0, "an already-trailed stop must never be reset by the backfill"


def test_ensure_signal_state_removes_a_ghost_real_position_instead_of_backfilling():
    # 2026-09-09, explicit user finding right after the self-heal first
    # shipped: DEEP.NS showed as REAL LIVE after already being exited -
    # Kotak shows no open position for it (a restart-race ghost, same
    # class _kotak_symbol_still_open already documents), so this must
    # DELETE the ghost real_positions row instead of resurrecting paper
    # tracking for a position that no longer exists.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn, symbol="DEEP.NS")
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("DEEP.NS",)).fetchone()
        with patch("main._kotak_symbol_still_open", return_value=False):
            created = main._ensure_signal_state_for_real_position(conn, real_row)
        assert created is False
        assert conn.execute("SELECT 1 FROM real_positions WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM signal_state WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None


def test_ensure_signal_state_still_backfills_on_a_transient_kotak_fetch_failure():
    # still_open() returning None (fetch failed, not confirmed closed)
    # must fail OPEN - same precedent _kotak_symbol_still_open's own
    # docstring establishes - not silently abandon a genuinely open
    # position over a transient API hiccup.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position(conn)
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("MEDICAMEQ.NS",)).fetchone()
        with patch("main._kotak_symbol_still_open", return_value=None):
            created = main._ensure_signal_state_for_real_position(conn, real_row)
        assert created is True
        assert conn.execute(
            "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", ("MEDICAMEQ.NS",)
        ).fetchone() is not None


def test_maybe_sync_real_stop_loss_self_heals_and_places_the_real_sl():
    """End-to-end: a real position with NO signal_state row (the exact bug
    reported live) must still get a real trailing-stop order placed once
    _maybe_sync_real_stop_loss runs, not silently return early."""
    _fresh_db()
    fake_kotak_real_orders = MagicMock()
    fake_kotak_real_orders.place_real_stop_loss.return_value = {
        "ok": True, "order_id": "999", "trigger_price": 285.57,
    }
    with closing(main.get_db()) as conn:
        _insert_real_position(conn, sl_order_id=None, sl_trigger_price=None)
        with patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
            main._maybe_sync_real_stop_loss(conn, "MEDICAMEQ.NS")

        # signal_state must now exist (the self-heal)
        row = conn.execute(
            "SELECT * FROM signal_state WHERE symbol = ? AND status = 'long'", ("MEDICAMEQ.NS",)
        ).fetchone()
        assert row is not None

        # and a real stop-loss order must have actually been placed
        fake_kotak_real_orders.place_real_stop_loss.assert_called_once()
        real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", ("MEDICAMEQ.NS",)).fetchone()
        assert real_row["sl_order_id"] == "999"
        assert real_row["sl_trigger_price"] == 285.57
