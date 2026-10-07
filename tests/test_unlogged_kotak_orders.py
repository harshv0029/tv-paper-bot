import sqlite3
import main


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE real_order_events (id INTEGER PRIMARY KEY, ts REAL, symbol TEXT, kotak_trading_symbol TEXT, "
              "leg TEXT, event TEXT, order_id TEXT, prev_state TEXT, new_state TEXT, detail TEXT)")
    return c


def test_logs_only_orders_without_a_row(monkeypatch):
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **k: None)
    c = _conn()
    c.execute("INSERT INTO real_order_events (ts, order_id) VALUES (1, 'A1')")
    rows = [{"nOrdNo": "A1", "trdSym": "X-EQ"},
            {"nOrdNo": "B2", "trdSym": "NYKAA-EQ", "trnsTp": "B", "prcTp": "SL", "qty": 1, "ordSt": "rejected",
             "rejRsn": "CAS session end", "ordDtTm": "07-Oct-2026 15:33:06"}]
    assert main._log_unlogged_kotak_orders(c, rows) == 1
    assert main._log_unlogged_kotak_orders(c, rows) == 0
    d = c.execute("SELECT detail FROM real_order_events WHERE order_id='B2'").fetchone()[0]
    assert "UNLOGGED" in d and "CAS session end" in d
