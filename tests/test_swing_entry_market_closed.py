"""B-1373: no real swing entry (shares or option leg) while NSE is closed; logged as skipped_market_closed."""
import sqlite3

import main


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE real_trades (ts REAL, day TEXT, symbol TEXT, kotak_trading_symbol TEXT, side TEXT, qty INT,"
              " price_est REAL, notional_inr REAL, status TEXT, order_id TEXT, detail TEXT, raw_response TEXT, strategy TEXT)")
    return c


def test_closed_session_blocks_before_viability_and_option_leg(monkeypatch):
    c = _db()
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_swing_real_entry_session_open", lambda: False)
    called = []
    monkeypatch.setattr(main, "_maybe_place_swing_option_leg", lambda *a, **k: called.append("opt"))
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: called.append("gate") or True)
    main._maybe_place_real_swing_entry(c, "TCS.NS", 10, 100.0, 95.0, "gap_and_go")
    assert called == []
    assert c.execute("SELECT status FROM real_trades").fetchall() == [("skipped_market_closed",)]
    assert main._viability_rejections_today(c)["total"] == 0


def test_session_helper_needs_trading_day_and_hours(monkeypatch):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: False)
    assert main._swing_real_entry_session_open() is False
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    assert main._swing_real_entry_session_open() is True
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: False)
    assert main._swing_real_entry_session_open() is False
