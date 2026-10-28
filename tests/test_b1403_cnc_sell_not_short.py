"""B-1403 (NHPC 28 Oct 2026): a CNC net-short row is a delivery holding sold today, never a short - even when holdings()
does not list it (T1 / fetch failure). Before the fix the reconcile adopted a phantom short and its BUY stop bought 1 share."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import main

CNC_SOLD = {"exSeg": "nse_cm", "trdSym": "NHPC-EQ", "flBuyQty": "0", "flSellQty": "1", "sellAmt": "72.50", "prod": "CNC"}
MIS_SHORT = dict(CNC_SOLD, prod="MIS")
SELL = {"actId": "X", "algId": "99999", "ordSrc": "ADMINCPPAPI_NEOTRADEAPI", "trdSym": "NHPC-EQ", "trnsTp": "S",
        "prcTp": "MKT", "ordSt": "complete", "nOrdNo": "1001", "qty": 1, "prod": "CNC"}


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def test_helper():
    assert main._is_delivery_sell_not_short(CNC_SOLD, -1) is True
    assert main._is_delivery_sell_not_short(MIS_SHORT, -1) is False
    assert main._is_delivery_sell_not_short(CNC_SOLD, 1) is False


def test_short_probes_ignore_sold_delivery_row():
    with patch("kotak_neo.positions", return_value={"data": [CNC_SOLD]}):
        assert main._kotak_symbol_still_open_short("NHPC-EQ") is False
        assert main._real_held_qty_short("NHPC-EQ") == 0.0
    with patch("kotak_neo.positions", return_value={"data": [MIS_SHORT]}):
        assert main._kotak_symbol_still_open_short("NHPC-EQ") is True
        assert main._real_held_qty_short("NHPC-EQ") == 1.0


def test_reconcile_never_adopts_or_stops_a_sold_holding_without_holdings_listing():
    _fresh_db()
    fake_orders = MagicMock()
    with patch("kotak_neo.positions", return_value={"data": [CNC_SOLD]}), \
         patch("kotak_neo.holdings", return_value={"data": []}), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": [SELL]}), \
         patch.dict("sys.modules", {"kotak_real_orders": fake_orders}):
        result = main._reconcile_real_positions_core(adopt="*")
    fake_orders.place_real_short_stop_loss.assert_not_called()
    assert not [a for a in result.get("adopted", []) if a.get("side") == "short"]
    with closing(main.get_db()) as c:
        assert c.execute("SELECT 1 FROM real_positions_short").fetchone() is None
