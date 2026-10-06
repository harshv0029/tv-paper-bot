import sqlite3
import main




def test_reroute_moves_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    conn = main.get_db()
    monkeypatch.setattr(main, "_sync_real_positions_external", lambda c: None)
    monkeypatch.setattr(main, "_sync_real_positions_swing_external", lambda c: None)
    monkeypatch.setattr(main, "_sync_signal_state_swing_external", lambda c: None)
    conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                 "VALUES ('RVNL.NS','RVNL-EQ',2,199.23,1.0,'2026-10-06')")
    conn.commit()
    row = conn.execute("SELECT * FROM real_positions WHERE symbol='RVNL.NS'").fetchone()
    assert main._reroute_orphan_intraday_to_swing(conn, row) is True
    assert conn.execute("SELECT COUNT(*) FROM real_positions").fetchone()[0] == 0
    sw = conn.execute("SELECT * FROM real_positions_swing WHERE symbol='RVNL.NS'").fetchone()
    assert sw["stop_loss"] == round(199.23 * 0.97, 2)
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0] == 1
    ev = conn.execute("SELECT detail FROM real_order_events WHERE event='moved_to_swing'").fetchone()
    assert ev["detail"].startswith("reason:")


def test_reroute_leaves_strategy_or_protected_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    conn = main.get_db()
    conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, strategy) "
                 "VALUES ('A.NS','A-EQ',1,10,1.0,'2026-10-06','universal_score')")
    conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, sl_order_id) "
                 "VALUES ('B.NS','B-EQ',1,10,1.0,'2026-10-06','123')")
    conn.commit()
    for sym in ("A.NS", "B.NS"):
        row = conn.execute("SELECT * FROM real_positions WHERE symbol=?", (sym,)).fetchone()
        assert main._reroute_orphan_intraday_to_swing(conn, row) is False
