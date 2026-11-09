"""B-1518: NSE session open/close known per day (regular, Muhurat/special, tick-only) for intraday and swing."""
import datetime as dt
import main

MUHURAT = dt.datetime(2026, 11, 8, 14, 30)      # Sun, special session 14:20-15:30 IST
MONDAY = dt.datetime(2026, 11, 9, 10, 0)        # regular trading day
HOLIDAY = dt.datetime(2026, 11, 10, 10, 0)      # NSE holiday


def test_session_today_kinds(monkeypatch):
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: False)
    assert main.nse_session_today(MUHURAT) == {"source": "special", "open_min": 860, "close_min": 930, "squareoff_min": 914}
    assert main.nse_session_today(MONDAY)["source"] == "regular"
    assert main.nse_session_today(HOLIDAY) is None
    assert main.nse_session_today(dt.datetime(2026, 11, 7, 10, 0)) is None  # plain Saturday


def test_tick_only_session_has_unknown_close(monkeypatch):
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: True)
    s = main.nse_session_today(HOLIDAY)
    assert s["source"] == "tick" and s["close_min"] is None
    assert main._nse_session_minutes("TCS.NS", 330, 555, 930, 914, HOLIDAY)[3] is False
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 10, 16, 0)) is False


def test_intraday_minutes_follow_special_session(monkeypatch):
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: False)
    assert main._nse_session_minutes("TCS.NS", 330, 555, 930, 914, MUHURAT) == (860, 930, 914, True)
    assert main._nse_session_minutes("TCS.NS", 330, 555, 930, 914, MONDAY) == (555, 930, 914, True)
    # MCX / non-IST configs never change
    assert main._nse_session_minutes("GC=F", 330, 540, 1410, 1400, MUHURAT) == (540, 1410, 1400, True)
    assert main._nse_session_minutes("AAPL", -240, 570, 960, 950, MUHURAT) == (570, 960, 950, True)


def test_daily_bar_complete_only_after_todays_close(monkeypatch):
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: False)
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 9, 9, 5)) is False   # pre-open: use previous session
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 9, 15, 0)) is False
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 9, 15, 31)) is True
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 8, 15, 31)) is True   # Muhurat bar complete
    assert main.nse_session_closed_for_day(dt.datetime(2026, 11, 8, 14, 0)) is False   # Muhurat not started


def test_swing_cutoff_follows_session_close(monkeypatch):
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: False)
    monkeypatch.setattr(main, "SWING_REAL_ENTRY_CUTOFF_MIN", 914)
    assert main.swing_entry_cutoff_min(MONDAY) == 914
    assert main.swing_entry_cutoff_min(MUHURAT) == 914
    monkeypatch.setitem(main.NSE_SPECIAL_SESSIONS, "2026-11-15", (18 * 60, 19 * 60))
    assert main.swing_entry_cutoff_min(dt.datetime(2026, 11, 15, 18, 10)) == 19 * 60 - 16


def test_auto_core_refuses_intraday_on_tick_only_day(monkeypatch):
    monkeypatch.setattr(main, "_nse_session_minutes", lambda *a, **k: (555, 930, 914, False))
    r = main._auto_signal_core(symbol="TCS.NS", capital=10000.0)
    assert r["status"] == "session_close_unknown"


def test_swing_scan_source_uses_session_close():
    import inspect
    src = inspect.getsource(main)
    assert "or not nse_session_closed_for_day()" in src
    assert "_n.hour * 60 + _n.minute >= SWING_REAL_ENTRY_CUTOFF_MIN" not in src
