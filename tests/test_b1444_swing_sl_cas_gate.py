"""B-1444 (IOC, 2 Nov 2026: 6 rejects 15:22-15:31 IST "SL AND SL-M ORDERS NOT ALLOWED IN CAS SESSION"): after the
exchange's 15:15 IST cancel, swing SL (re)placement retries must not reach Kotak until the 09:15 IST open."""
import inspect
import os
import sqlite3
import tempfile
import time
import types

import kotak_real_orders as kro
import main


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE real_positions_swing (symbol TEXT, kotak_trading_symbol TEXT, qty INTEGER, "
                 "entry_price REAL, stop_loss REAL, strategy TEXT, sl_order_id TEXT, sl_trigger_price REAL, "
                 "opened_at REAL, day TEXT)")
    conn.execute("INSERT INTO real_positions_swing VALUES ('IOC.NS','IOC-EQ',10,140.0,135.0,'gap_and_go',NULL,NULL,?,?)",
                 (time.time(), "2026-11-02"))
    conn.commit()
    return conn


def test_swing_sl_retry_skipped_in_cas_window(monkeypatch):
    conn = _db()
    calls = []
    monkeypatch.setattr(kro, "ensure_resting_sl", lambda *a, **k: calls.append(a) or {"ok": False})
    monkeypatch.setattr(main, "_swing_stop_floored", lambda conn, sym, px: px)
    monkeypatch.setattr(main, "_swing_stop_breached_exit", lambda *a, **k: False)
    monkeypatch.setattr(main, "_exchange_purge_window", lambda now_ist=None: True)
    main._maybe_sync_real_swing_stop_loss(conn)
    assert calls == []


def test_ensure_resting_sl_never_places_fresh_after_1515(monkeypatch):
    # no live SL at Kotak (the exchange cancelled it at 15:15): the old code placed a fresh one, which Kotak rejects
    client = types.SimpleNamespace(order_report=lambda: {"data": []})
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: client)
    monkeypatch.setattr(kro, "_in_closing_session", lambda: True)
    placed = []
    monkeypatch.setattr(kro, "place_real_stop_loss", lambda *a, **k: placed.append(a) or {"ok": True, "order_id": "9"})
    res = kro.ensure_resting_sl("IOC-EQ", 10, 135.0)
    assert placed == [] and res["ok"] is False and res["action"] == "skipped_closing_session"


def test_ensure_resting_sl_unreadable_book_no_place_after_1515(monkeypatch):
    def _boom():
        raise RuntimeError("order book down")
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: types.SimpleNamespace(order_report=_boom))
    monkeypatch.setattr(kro, "_in_closing_session", lambda: True)
    placed = []
    monkeypatch.setattr(kro, "place_real_stop_loss", lambda *a, **k: placed.append(a) or {"ok": True, "order_id": "9"})
    assert kro.ensure_resting_sl("IOC-EQ", 10, 135.0)["action"] == "skipped_closing_session" and placed == []


def test_ensure_resting_sl_still_places_in_session(monkeypatch):
    client = types.SimpleNamespace(order_report=lambda: {"data": []})
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: client)
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    monkeypatch.setattr(kro, "place_real_stop_loss",
                        lambda s, q, t: {"ok": True, "order_id": "9", "trigger_price": t})
    assert kro.ensure_resting_sl("IOC-EQ", 10, 135.0)["action"] == "placed"


def test_swing_gates_use_purge_window_and_exits_untouched():
    assert "_exchange_purge_window()" in inspect.getsource(main._maybe_sync_real_swing_stop_loss)
    assert "_exchange_purge_window()" in inspect.getsource(main._heal_real_swing_short_sl)
    assert "_exchange_purge_window()" in inspect.getsource(main._reconcile_real_positions_core)
    assert "_exchange_purge_window" not in inspect.getsource(main._maybe_place_real_swing_exit)
    assert "_exchange_purge_window" not in inspect.getsource(main._maybe_place_real_short_exit)
