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


def _short_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE real_positions_short (symbol TEXT, kotak_trading_symbol TEXT, qty INT, sl_order_id TEXT, sl_trigger_price REAL, strategy TEXT)")
    conn.execute("INSERT INTO real_positions_short VALUES ('YESBANK.NS','YESBANK-EQ',20,NULL,NULL,'x')")
    return conn


def test_no_cover_sent_when_nse_closed_and_kotak_unreadable(monkeypatch):
    """B-313 second half: 01:00 IST loops (10-13/16/23/28) sent market covers Kotak rejected (no LTP)."""
    conn = _short_conn()
    monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda t: None)  # adapter logged off
    monkeypatch.setattr(main, "category_market_open", lambda cat, now=None: False)
    monkeypatch.setattr(main, "_SHORT_COVER_CLOSED_LOGGED", set())
    events = []
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: events.append(a[3]))
    import kotak_real_orders
    monkeypatch.setattr(kotak_real_orders, "place_real_short_cover", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")))
    monkeypatch.setattr(kotak_real_orders, "cancel_real_order", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not cancel")))
    main._maybe_place_real_short_exit(conn, "YESBANK.NS", reason="emergency test")
    main._maybe_place_real_short_exit(conn, "YESBANK.NS", reason="emergency test")
    assert events == ["skipped_market_closed"]  # logged once per symbol per IST day, no order
    assert conn.execute("SELECT COUNT(*) FROM real_positions_short").fetchone()[0] == 1  # row kept for the open


def test_cover_sent_when_nse_open(monkeypatch):
    conn = _short_conn()
    monkeypatch.setattr(main, "_kotak_symbol_still_open_short", lambda t: True)
    monkeypatch.setattr(main, "category_market_open", lambda cat, now=None: True)
    monkeypatch.setattr(main, "_sync_real_positions_short_external", lambda c: None)
    monkeypatch.setattr(main, "_log_real_attempt", lambda *a, **k: None)
    events = []
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: events.append(a[3]))
    import kotak_real_orders
    sent = []
    monkeypatch.setattr(kotak_real_orders, "place_real_short_cover", lambda t, q: sent.append((t, q)) or {"ok": True, "order_id": "1"})
    main._maybe_place_real_short_exit(conn, "YESBANK.NS", reason="emergency test")
    assert sent == [("YESBANK-EQ", 20)]
    assert events[-1] == "confirmed"
