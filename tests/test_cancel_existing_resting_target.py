"""Tests for kotak_real_orders.cancel_existing_resting_target (2026-09-21,
explicit user instruction: "before placing next order when one entered
position there and one same next order of same asset in order book then
first check which order there... cancel that from order book and then
validate and then place new order"). Target-side mirror of the existing
cancel_existing_resting_sl (2026-09-08 AGL lost-tracking incident) - see
kotak_real_orders.py's own module docstring for why a blind sweep of
resting limit sells would be unsafe (could cancel a genuine MANUAL order
on this same account) and how the bot-order tag (ordSrc/algId) fixes
that."""
from unittest.mock import MagicMock, patch

import kotak_real_orders


def _order_report_rows(rows):
    client = MagicMock()
    client.order_report.return_value = {"data": rows}
    return client


BOT_TAG = {"ordSrc": "ADMINCPPAPI_NEOTRADEAPI", "algId": "99999"}
MANUAL_TAG = {"ordSrc": "ADMINCPPAPI_MOB", "algId": "NA"}


def test_cancels_a_bot_placed_resting_target_for_the_symbol():
    row = {"trdSym": "RELIANCE-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open",
           "nOrdNo": "T1", **BOT_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        result = kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_called_once_with("T1")
    assert result["cancelled"] == ["T1"]


def test_never_cancels_a_manually_placed_limit_sell():
    row = {"trdSym": "RELIANCE-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open",
           "nOrdNo": "M1", **MANUAL_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        result = kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_not_called()
    assert result["cancelled"] == []


def test_ignores_orders_for_a_different_symbol():
    row = {"trdSym": "TCS-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open",
           "nOrdNo": "T2", **BOT_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        result = kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_not_called()
    assert result["cancelled"] == []


def test_ignores_a_buy_side_order():
    row = {"trdSym": "RELIANCE-EQ", "trnsTp": "B", "prcTp": "L", "ordSt": "open",
           "nOrdNo": "T3", **BOT_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_not_called()


def test_ignores_a_stop_loss_order_type():
    # SL orders are cancel_existing_resting_sl's own job - a "SL"/"SL-M"
    # price-type row must never be double-cancelled by the target sweep.
    row = {"trdSym": "RELIANCE-EQ", "trnsTp": "S", "prcTp": "SL-M", "ordSt": "open",
           "nOrdNo": "SL1", **BOT_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_not_called()


def test_ignores_already_terminal_orders():
    row = {"trdSym": "RELIANCE-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "complete",
           "nOrdNo": "T4", **BOT_TAG}
    client = _order_report_rows([row])
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_real_orders.cancel_real_order") as mock_cancel:
        kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    mock_cancel.assert_not_called()


def test_order_book_fetch_failure_fails_open_not_raises():
    with patch("kotak_neo.login", side_effect=Exception("network error")):
        result = kotak_real_orders.cancel_existing_resting_target("RELIANCE-EQ")
    assert result["cancelled"] == []
    assert "network error" in result["detail"]
