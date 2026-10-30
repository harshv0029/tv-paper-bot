"""B-1429: per-tick SL sync must compare the paper stop on Kotak's own tick.

Live DABUR short, 30 Oct 2026 09:25 IST: the resting BUY stop sat at 383.05
(kotak_real_orders rounds every trigger to the 0.05 tick), the paper stop was
383.03, and _maybe_sync_real_stop_loss_short read 383.03 < 383.05 as a
favorable trail, cancelled the live stop and re-placed the identical 383.05
order (~3 s with no stop). The long sync had the same sub-tick churn.
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

_LIVE_SL = {"stat": "Ok", "data": [{"nOrdNo": "SL-OLD", "ordSt": "trigger pending", "rejRsn": "--"}], "stCode": 200}


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _short(conn, paper_stop, trigger=383.05):
    today = main.ist_now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
        "opened_at, day, sl_order_id, sl_trigger_price, strategy) VALUES "
        "('DABUR.NS', 'DABUR-EQ', 1, 365.5, 'E1', ?, ?, 'SL-OLD', ?, 'chan_gap')",
        (main.time.time(), today, trigger))
    conn.execute(
        "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, "
        "qty, entry_ts, fx_to_inr, interval) VALUES ('DABUR.NS', ?, 'short', 365.5, ?, 383.03, 340.0, 1, ?, 1.0, '1d')",
        (today, paper_stop, main.time.time()))
    conn.commit()


def _long(conn, paper_stop, trigger=97.0):
    today = main.ist_now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, "
        "sl_order_id, sl_trigger_price) VALUES ('ASHOKLEY.NS', 'ASHOKLEY-EQ', 2, 100.0, 'E1', ?, ?, 'SL-OLD', ?)",
        (main.time.time(), today, trigger))
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
        "entry_ts, fx_to_inr, interval) VALUES ('ASHOKLEY.NS', ?, 'long', 100.0, ?, 97.0, 110.0, 2, ?, 1.0, '5m')",
        (today, paper_stop, main.time.time()))
    conn.commit()


_SHORT_POS = {"data": [{"trdSym": "DABUR-EQ", "exSeg": "nse_cm", "flBuyQty": "0", "flSellQty": "1"}]}
_LONG_POS = {"data": [{"trdSym": "ASHOKLEY-EQ", "exSeg": "nse_cm", "flBuyQty": "2", "flSellQty": "0"}]}


def _run_short(paper_stop, place_ret=None):
    _fresh_db()
    with closing(main.get_db()) as conn:
        _short(conn, paper_stop)
        with patch("kotak_real_orders._tick_size_for", return_value=0.05), \
             patch("kotak_neo.positions", return_value=_SHORT_POS), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}) as c, \
             patch("kotak_real_orders.place_real_short_stop_loss", return_value=place_ret) as p:
            main._maybe_sync_real_stop_loss_short(conn, "DABUR.NS")
        row = conn.execute("SELECT * FROM real_positions_short WHERE symbol = 'DABUR.NS'").fetchone()
        return c, p, row


def _run_long(paper_stop, place_ret=None):
    _fresh_db()
    with closing(main.get_db()) as conn:
        _long(conn, paper_stop)
        with patch("kotak_real_orders._tick_size_for", return_value=0.05), \
             patch("kotak_neo.positions", return_value=_LONG_POS), \
             patch("kotak_neo.order_report", return_value=_LIVE_SL), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}) as c, \
             patch("kotak_real_orders.place_real_stop_loss", return_value=place_ret) as p:
            main._maybe_sync_real_stop_loss(conn, "ASHOKLEY.NS")
        row = conn.execute("SELECT * FROM real_positions WHERE symbol = 'ASHOKLEY.NS'").fetchone()
        return c, p, row


def test_short_sub_tick_trail_does_not_cancel_or_replace():
    c, p, row = _run_short(383.03)  # rounds to the 383.05 already resting
    c.assert_not_called()
    p.assert_not_called()
    assert row["sl_order_id"] == "SL-OLD" and row["sl_trigger_price"] == 383.05


def test_short_full_tick_move_replaces_once_and_stores_rounded_trigger():
    c, p, row = _run_short(382.98, {"ok": True, "order_id": "SL-NEW", "trigger_price": 383.0})
    c.assert_called_once_with("SL-OLD")
    p.assert_called_once()
    assert p.call_args[0][2] == 383.0  # sent on the tick, not 382.98
    assert row["sl_order_id"] == "SL-NEW" and row["sl_trigger_price"] == 383.0


def test_long_sub_tick_trail_does_not_cancel_or_replace():
    c, p, row = _run_long(97.02)  # rounds to the 97.00 already resting
    c.assert_not_called()
    p.assert_not_called()
    assert row["sl_trigger_price"] == 97.0


def test_long_full_tick_move_replaces_once_and_stores_rounded_trigger():
    c, p, row = _run_long(97.04, {"ok": True, "order_id": "SL-NEW", "trigger_price": 97.05})
    c.assert_called_once_with("SL-OLD")
    p.assert_called_once()
    assert p.call_args[0][2] == 97.05
    assert row["sl_order_id"] == "SL-NEW" and row["sl_trigger_price"] == 97.05


def test_helper_matches_placement_rounding():
    with patch("kotak_real_orders._tick_size_for", return_value=0.05):
        assert main._real_stop_on_tick("DABUR-EQ", 383.03) == 383.05
        assert main._real_stop_on_tick("DABUR-EQ", 382.98) == 383.0
    with patch("kotak_real_orders._tick_size_for", side_effect=Exception("down")):
        assert main._real_stop_on_tick("X-EQ", 101.07) == 101.05
