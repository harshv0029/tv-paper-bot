"""B-295 part 4: swing/CNC sells (not in positions-derived closed trades) surface from Kotak's order book."""
import os, tempfile
from contextlib import closing
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()


def test_sell_fill_listed_with_reason_and_swing_entry_pnl():
    _db()
    day = main.ist_now().strftime("%d-%b-%Y")
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_order_events (ts,symbol,kotak_trading_symbol,leg,event,order_id,detail) "
                  "VALUES (1,'X.NS','X-EQ','exit','placed','77','reason: trail stop hit; x')")
        c.commit()
        rows = [
            {"nOrdNo": "77", "trdSym": "X-EQ", "trnsTp": "S", "ordSt": "complete", "fldQty": "2", "avgPrc": "110", "ordDtTm": f"{day} 13:54:00"},
            {"nOrdNo": "78", "trdSym": "Y-EQ", "trnsTp": "S", "ordSt": "complete", "fldQty": "1", "avgPrc": "50", "ordDtTm": f"{day} 13:00:00"},
            {"nOrdNo": "79", "trdSym": "Z-EQ", "trnsTp": "B", "ordSt": "complete", "fldQty": "1", "avgPrc": "5", "ordDtTm": f"{day} 13:00:00"},
            {"nOrdNo": "80", "trdSym": "W-EQ", "trnsTp": "S", "ordSt": "rejected", "fldQty": "0", "avgPrc": "0", "ordDtTm": f"{day} 13:00:00"},
        ]
        out = main._kotak_exit_fills_today(rows, {"Y-EQ"}, c)
    assert [o["symbol"] for o in out] == ["X-EQ"]
    assert out[0]["exit_reason"] == "trail stop hit" and out[0]["pnl_inr"] is None
