"""Tests for short-side auto-heal (2026-09-30, explicit user instruction
after the MFSL.NS incident: "For short positions and all live positions
make it auto heal"). Before this, short auto-adopt was a documented,
real gap (main.py's own 2026-09-29 comment: "short auto-adopt is a real,
known gap, not silently mishandled") - an untracked short, or a tracked
short whose real_positions_short row lost its sl_order_id, had NO
self-healing path at all, unlike the long side (adopt="*" every 5 min +
synchronous governance-backfill SL placement, in place since 2026-09-08).

This mirrors that same long-side machinery for shorts:
- _kotak_symbol_still_open_short (short mirror of _kotak_symbol_still_open
  - the long version's `fl_buy > 0` check would ALWAYS return False for a
  genuine short, so it could never be reused as-is)
- _ensure_signal_state_for_real_position_short (short mirror of
  _ensure_signal_state_for_real_position)
- _reconcile_real_positions_core's own adopt block and governance-backfill
  loop, both now short-aware

Run: pytest tests/test_short_position_auto_heal.py -v
"""
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


def _insert_real_position_short(conn, symbol="TCS.NS", entry_price=2100.0, qty=1,
                                 sl_order_id=None, sl_trigger_price=None, strategy="range_short_staged_ladder"):
    conn.execute(
        "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol, symbol.replace(".NS", "-EQ"), qty, entry_price, "1", main.time.time(),
         main.ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price, strategy),
    )
    conn.commit()


# ---- _kotak_symbol_still_open_short ----------------------------------------

def test_still_open_short_true_when_net_short_at_kotak():
    fake_positions = {"data": [
        {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "1"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        assert main._kotak_symbol_still_open_short("TCS-EQ") is True


def test_still_open_short_false_when_fully_squared_off():
    fake_positions = {"data": [
        {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "1", "flSellQty": "1"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        assert main._kotak_symbol_still_open_short("TCS-EQ") is False


def test_still_open_short_false_when_symbol_absent():
    with patch("kotak_neo.positions", return_value={"data": []}):
        assert main._kotak_symbol_still_open_short("TCS-EQ") is False


def test_still_open_short_none_on_fetch_failure():
    with patch("kotak_neo.positions", side_effect=Exception("network down")):
        assert main._kotak_symbol_still_open_short("TCS-EQ") is None


def test_still_open_short_a_genuine_long_on_the_same_symbol_is_not_a_short():
    # flBuyQty > flSellQty is a LONG, not a short - must not be conflated.
    fake_positions = {"data": [
        {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "flBuyQty": "1", "flSellQty": "0"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        assert main._kotak_symbol_still_open_short("TCS-EQ") is False


# ---- _ensure_signal_state_for_real_position_short --------------------------

def test_ensure_signal_state_short_creates_a_row_when_missing():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn)
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
        created = main._ensure_signal_state_for_real_position_short(conn, real_row)
        assert created is True
        row = conn.execute(
            "SELECT * FROM signal_state_short WHERE symbol = ? AND status = 'short'", ("TCS.NS",)
        ).fetchone()
        assert row is not None
        assert row["entry_price"] == 2100.0
        # A short's stop sits ABOVE entry (mirror of the long's below-entry stop).
        watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in main.WATCHLIST}
        stop_pct = watchlist_by_symbol.get("TCS.NS", {}).get("stop_pct", 2.0)
        assert row["stop_loss"] == round(2100.0 * (1 + stop_pct / 100), 2)
        assert row["stop_loss"] > 2100.0
        assert row["strategy"] == "range_short_staged_ladder"


def test_ensure_signal_state_short_returns_false_and_does_not_overwrite_an_existing_row():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn)
        conn.execute(
            "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
            "VALUES (?, ?, 'short', ?, ?, ?, ?, ?, ?, 1.0, '5m')",
            ("TCS.NS", main.ist_now().strftime("%Y-%m-%d"), 2100.0, 2150.0, 2150.0, 2000.0, 1, main.time.time()),
        )
        conn.commit()
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
        created = main._ensure_signal_state_for_real_position_short(conn, real_row)
        assert created is False
        row = conn.execute(
            "SELECT * FROM signal_state_short WHERE symbol = ? AND status = 'short'", ("TCS.NS",)
        ).fetchone()
        assert row["stop_loss"] == 2150.0, "an already-trailed stop must never be reset by the backfill"


def test_ensure_signal_state_short_removes_a_ghost_position_instead_of_backfilling():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn, symbol="DEEP.NS")
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("DEEP.NS",)).fetchone()
        with patch("main._kotak_symbol_still_open_short", return_value=False):
            created = main._ensure_signal_state_for_real_position_short(conn, real_row)
        assert created is False
        assert conn.execute("SELECT 1 FROM real_positions_short WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM signal_state_short WHERE symbol = ?", ("DEEP.NS",)).fetchone() is None


def test_ensure_signal_state_short_still_backfills_on_a_transient_fetch_failure():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn)
        real_row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
        with patch("main._kotak_symbol_still_open_short", return_value=None):
            created = main._ensure_signal_state_for_real_position_short(conn, real_row)
        assert created is True


# ---- End-to-end via _reconcile_real_positions_core --------------------------

_BOT_SHORT_ENTRY = {
    "actId": "X", "algId": "99999", "ordSrc": "ADMINCPPAPI_NEOTRADEAPI",
    "trdSym": "TCS-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "complete",
    "nOrdNo": "1001", "qty": 1,
}


def test_reconcile_adopts_an_untracked_bot_placed_short_into_real_positions_short():
    _fresh_db()
    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "TCS-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "2100.00"},
    ]}
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": [_BOT_SHORT_ENTRY]}):
        result = main._reconcile_real_positions_core(adopt="TCS-EQ")

    assert result["adopted_count"] == 1
    assert result["adopted"][0]["side"] == "short"
    assert result["adopted"][0]["entry_price"] == 2100.0
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
    assert row is not None
    assert row["qty"] == 1
    assert row["entry_price"] == 2100.0


def test_reconcile_places_a_real_short_sl_synchronously_after_adopting():
    # The full "auto heal" chain: adopt -> governance backfill creates
    # signal_state_short -> a real BUY-side stop gets placed in THIS same
    # call, not left for a scheduler tick that (for shorts) doesn't exist
    # yet to pick it up.
    _fresh_db()
    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "TCS-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "2100.00"},
    ]}
    fake_kotak_real_orders = MagicMock()
    fake_kotak_real_orders.place_real_short_stop_loss.return_value = {
        "ok": True, "order_id": "555", "trigger_price": 2142.0,
    }
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": [_BOT_SHORT_ENTRY]}), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
        result = main._reconcile_real_positions_core(adopt="TCS-EQ")

    fake_kotak_real_orders.place_real_short_stop_loss.assert_called_once()
    assert result["governance_backfilled_short_count"] == 1
    assert result["governance_backfilled_short"][0]["sl_placed"] is True
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
    assert row["sl_order_id"] == "555"
    assert row["sl_trigger_price"] == 2142.0


def test_reconcile_heals_an_already_tracked_short_missing_its_sl_every_run():
    # Not just freshly-adopted ones - ANY row in real_positions_short with
    # no sl_order_id gets one placed, every single reconcile call (no
    # `adopt` needed at all here).
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn, sl_order_id=None, sl_trigger_price=None)
    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "TCS-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "2100.00"},
    ]}
    fake_kotak_real_orders = MagicMock()
    fake_kotak_real_orders.place_real_short_stop_loss.return_value = {
        "ok": True, "order_id": "777", "trigger_price": 2142.0,
    }
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
        result = main._reconcile_real_positions_core(adopt=None)

    fake_kotak_real_orders.place_real_short_stop_loss.assert_called_once()
    assert result["governance_backfilled_short_count"] == 1
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = ?", ("TCS.NS",)).fetchone()
    assert row["sl_order_id"] == "777"


def test_reconcile_does_not_falsely_flag_a_just_healed_short_as_unprotected():
    # Regression test for the stale-order_rows fix: the unprotected-check
    # must re-fetch order_report AFTER the synchronous SL placement above,
    # not judge protection off the pre-placement snapshot from the top of
    # the function (which would still show no SL and wrongly alarm on the
    # very call that just fixed it).
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_short(conn, sl_order_id=None, sl_trigger_price=None)
    fake_positions = {"data": [
        {"exSeg": "nse_cm", "trdSym": "TCS-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "2100.00"},
    ]}
    fake_kotak_real_orders = MagicMock()
    fake_kotak_real_orders.place_real_short_stop_loss.return_value = {
        "ok": True, "order_id": "888", "trigger_price": 2142.0,
    }
    # First order_report call (top of function, before healing) shows no
    # SL yet; the SECOND call (right before the unprotected-check, after
    # healing) shows the freshly-placed one.
    order_report_calls = [
        {"data": []},
        {"data": [{"trdSym": "TCS-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "trigger pending"}]},
    ]
    with patch("kotak_neo.positions", return_value=fake_positions), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", side_effect=order_report_calls), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_kotak_real_orders}):
        result = main._reconcile_real_positions_core(adopt=None)

    assert result["unprotected_positions_count"] == 0
    assert result["unprotected_positions"] == []
