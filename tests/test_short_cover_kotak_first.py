"""B-313: a buy-to-cover is never sent when Kotak shows no short; the stale app row is cleared."""
import sqlite3
import main


def test_stale_short_row_cleared_without_order(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE real_positions_short (symbol TEXT, kotak_trading_symbol TEXT, qty INT, sl_order_id TEXT, sl_trigger_price REAL, strategy TEXT)")
    conn.execute("INSERT INTO real_positions_short VALUES ('NYKAA.NS','NYKAA-EQ',1,NULL,NULL,'x')")
    monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda t: False)
    monkeypatch.setattr(main, "_sync_real_positions_short_external", lambda c: None)
    events = []
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: events.append(a[3]))
    import kotak_real_orders
    monkeypatch.setattr(kotak_real_orders, "place_real_short_cover", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")))
    main._maybe_place_real_short_exit(conn, "NYKAA.NS", reason="emergency test")
    assert conn.execute("SELECT COUNT(*) FROM real_positions_short").fetchone()[0] == 0
    assert events == ["stale_row_cleared"]
