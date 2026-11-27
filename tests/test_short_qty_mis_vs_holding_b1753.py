"""B-1753 (27-Nov BANKINDIA): a 7-share MIS short was netted against a 2-share delivery holding of the same symbol
(B-306 netting) to 5; the cover bought 5 and Kotak squared off the other 2 at 15:05. An MIS row is never netted,
the short qty read skips CNC rows, and the cover is sized from Kotak's live short qty."""
import os
import sys
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import main

SYM, TRD = "TESTBANK.NS", "TESTBANK-EQ"


def test_netting_skips_mis_rows_only():
    f = main._net_sold_delivery_holding
    hold = {TRD: 2}
    assert f({"trdSym": TRD, "prod": "MIS"}, -7.0, hold) == -7.0  # genuine intraday short
    assert f({"trdSym": TRD, "prod": "CNC"}, -2.0, hold) == 0.0   # sold delivery share (B-306)
    assert f({"trdSym": TRD}, -3.0, hold) == -1.0                 # unknown product keeps the old netting
    assert f({"trdSym": "OTHER-EQ", "prod": "CNC"}, -2.0, hold) == -2.0


def _kotak(rows):
    m = MagicMock()
    m.positions.return_value = {"data": rows}
    return patch.dict(sys.modules, {"kotak_neo": m})


def test_short_qty_read_skips_delivery_row():
    rows = [{"trdSym": TRD, "exSeg": "nse_cm", "prod": "CNC", "flBuyQty": "0", "flSellQty": "0"},
            {"trdSym": TRD, "exSeg": "nse_cm", "prod": "MIS", "flBuyQty": "0", "flSellQty": "7"}]
    with _kotak(rows):
        assert main._real_held_qty_short(TRD) == 7.0


def test_cover_is_sized_from_kotak_live_qty(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                  "opened_at, day, strategy) VALUES (?, ?, 5, 168.23, 'E', 0, '2026-11-27', 't')", (SYM, TRD))
        c.commit()
        monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda t: True)
        monkeypatch.setattr(main, "_nse_closed_for_short_cover", lambda: False)
        monkeypatch.setattr(main, "_real_held_qty_short", lambda t: 7.0)
        monkeypatch.setattr(main, "_sync_real_positions_short_external", lambda conn: None)
        kro = MagicMock()
        kro.place_real_short_cover.return_value = {"ok": True, "order_id": "X", "fill_price": 160.0}
        with patch.dict(sys.modules, {"kotak_real_orders": kro}):
            main._maybe_place_real_short_exit(c, SYM, reason="test")
    q = kro.place_real_short_cover.call_args[0][1]
    assert q == 7 and isinstance(q, int)
