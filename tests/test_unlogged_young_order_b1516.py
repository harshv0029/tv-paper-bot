"""B-1516: the UNLOGGED sweep skips Kotak orders younger than 30 s (app log row race)."""
import datetime as dt
import sqlite3

import main


def _ord_dt(ts):
    return (dt.datetime.utcfromtimestamp(ts) + dt.timedelta(minutes=main.IST_OFFSET_MIN)).strftime("%d-%b-%Y %H:%M:%S")


def test_too_young_helper():
    now = 1_794_800_000.0
    assert main._kotak_order_too_young(_ord_dt(now - 3), now=now)
    assert not main._kotak_order_too_young(_ord_dt(now - 120), now=now)
    assert not main._kotak_order_too_young("garbage", now=now)
    assert not main._kotak_order_too_young(None, now=now)


def test_sweep_skips_young_logs_old(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE real_order_events (id INTEGER PRIMARY KEY, ts REAL, symbol TEXT, kotak_trading_symbol "
                 "TEXT, leg TEXT, event TEXT, order_id TEXT, prev_state TEXT, new_state TEXT, detail TEXT)")
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **k: None)
    monkeypatch.setattr(main, "_flush_pending_kotak_sends", lambda *a, **k: None)
    import time
    now = time.time()
    rows = [{"nOrdNo": "Y1", "trdSym": "GROWW-EQ", "ordDtTm": _ord_dt(now - 2), "ordSt": "trigger pending"},
            {"nOrdNo": "O1", "trdSym": "WIPRO-EQ", "ordDtTm": _ord_dt(now - 600), "ordSt": "trigger pending"}]
    assert main._log_unlogged_kotak_orders(conn, rows) == 1
    ids = [r[0] for r in conn.execute("SELECT order_id FROM real_order_events")]
    assert ids == ["O1"]
