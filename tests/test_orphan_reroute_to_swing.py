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
    main._log_real_order_event(conn, "RVNL.NS", "sl", "placed", new_state="resting SELL trigger Rs197.50")
    conn.commit()
    row = conn.execute("SELECT * FROM real_positions WHERE symbol='RVNL.NS'").fetchone()
    assert main._reroute_orphan_intraday_to_swing(conn, row) is True
    assert conn.execute("SELECT COUNT(*) FROM real_positions").fetchone()[0] == 0
    sw = conn.execute("SELECT * FROM real_positions_swing WHERE symbol='RVNL.NS'").fetchone()
    assert sw["stop_loss"] == 197.50  # previous day's stop, stored
    st = conn.execute("SELECT * FROM signal_state_swing").fetchone()
    assert round(st["atr_at_entry"], 2) == 1.73  # R stored for the 0.5R gap rule and the trail
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


def _setup(tmp_path, monkeypatch, stop_state="resting SELL trigger Rs197.50"):
    import pandas as pd
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    conn = main.get_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_swing_external", "_sync_signal_state_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                 "VALUES ('RVNL.NS','RVNL-EQ',2,199.23,1.0,'2026-10-05')")
    main._log_real_order_event(conn, "RVNL.NS", "sl", "placed", new_state=stop_state)
    conn.commit()
    row = conn.execute("SELECT * FROM real_positions WHERE symbol='RVNL.NS'").fetchone()
    assert main._reroute_orphan_intraday_to_swing(conn, row)
    return conn, pd


def _bars(pd, open_px):
    today = main.ist_now().strftime("%Y-%m-%d")
    return pd.DataFrame({"Open": [open_px], "High": [open_px + 1], "Low": [open_px - 1], "Close": [open_px]},
                        index=pd.to_datetime([today]))


def test_gap_down_through_stop_resets_to_half_r_below_open(tmp_path, monkeypatch):
    conn, pd = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: _bars(pd, 190.0))
    row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol='RVNL.NS'").fetchone()
    stop = main._orphan_refresh_stop(conn, row)
    r = 199.23 - 197.50
    assert stop == round(190.0 - 0.5 * r, 2)
    ev = conn.execute("SELECT detail FROM real_order_events WHERE event='stop_gap_reset'").fetchone()
    assert ev["detail"].startswith("reason:")


def test_no_gap_keeps_carried_stop_and_waits_for_open(tmp_path, monkeypatch):
    conn, pd = _setup(tmp_path, monkeypatch)
    row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol='RVNL.NS'").fetchone()
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: _bars(pd, 199.0))
    assert main._orphan_refresh_stop(conn, row) == 197.50
    empty = _bars(pd, 199.0)
    empty.index = empty.index - pd.Timedelta(days=1)  # no bar for today yet
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: empty)
    assert main._orphan_refresh_stop(conn, row) is None


def test_trail_is_one_r_behind_peak_close():
    assert main._swing_strategy_stop_level(main.ORPHAN_SWING_STRATEGY_TAG, 197.5, 1.73, 210.0) == 210.0 - 1.73


def test_every_order_event_has_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    conn = main.get_db()
    main._log_real_order_event(conn, "X.NS", "sl", "placed")
    main._log_real_order_event(conn, "X.NS", "weird", "thing")
    for (d,) in conn.execute("SELECT detail FROM real_order_events").fetchall():
        assert d.startswith("reason: ") and len(d) > 12


def test_stop_falls_back_to_latest_kotak_sl_order_when_no_app_event(tmp_path, monkeypatch):
    import kotak_neo
    rows = [
        {"trdSym": "RVNL-EQ", "trnsTp": "S", "prcTp": "SL-M", "trgPrc": "190.00", "ordDtTm": "05-Oct-2026 10:00:00"},
        {"trdSym": "RVNL-EQ", "trnsTp": "S", "prcTp": "SL-M", "trgPrc": "196.40", "ordDtTm": "06-Oct-2026 09:30:00"},
        {"trdSym": "OTHER-EQ", "trnsTp": "S", "prcTp": "SL-M", "trgPrc": "5.00", "ordDtTm": "06-Oct-2026 11:00:00"},
    ]
    monkeypatch.setattr(kotak_neo, "order_report", lambda *a, **k: {"data": rows}, raising=False)
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    conn = main.get_db()
    conn.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                 "VALUES ('RVNL.NS','RVNL-EQ',2,199.23,1.0,'2026-10-05')")
    conn.commit()
    assert main._orphan_prev_day_stop(conn, "RVNL.NS", 199.23) == (196.40, "most recent SL order in Kotak's order book for this stock")
