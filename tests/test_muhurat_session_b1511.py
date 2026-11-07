"""B-1511: Muhurat 2026-11-08 (Sunday) 14:20-15:30 IST is an NSE trading session for every NSE gate."""
import datetime as dt

import main

SUN = dt.date(2026, 11, 8)


def _at(h, m, day=SUN):
    return dt.datetime.combine(day, dt.time(h, m))


def test_trading_day_and_session_window():
    assert main.is_nse_trading_day("2026-11-08")
    assert not main.is_nse_trading_day("2026-11-07")  # Saturday stays closed
    assert not main.is_nse_trading_day("2026-11-10")  # holiday stays closed
    assert main.nse_special_session(SUN) == (860, 930)


def test_closed_day_only_outside_window():
    assert main._nse_closed_day(_at(10, 0))
    assert not main._nse_closed_day(_at(14, 20))
    assert not main._nse_closed_day(_at(15, 30))
    assert main._nse_closed_day(_at(15, 31))
    assert main._nse_closed_day(_at(14, 30, dt.date(2026, 11, 7)))  # Saturday


def test_symbol_filter_nse_only():
    t = _at(14, 30)
    assert not main._nse_closed_day(t, "RELIANCE.NS")
    assert not main._nse_closed_day(t, "^NSEI")
    assert main._nse_closed_day(t, "GC=F")  # MCX proxy
    assert main._nse_closed_day(t, "AAPL")  # US


def test_purge_window_and_protect_window():
    assert main._exchange_purge_window(_at(14, 0))
    assert not main._exchange_purge_window(_at(14, 20))
    assert not main._exchange_purge_window(_at(15, 14))
    assert main._exchange_purge_window(_at(15, 15))
    assert main._in_open_protect_window(_at(14, 25))
    assert not main._in_open_protect_window(_at(14, 36))
    # a normal weekday is unchanged
    assert not main._exchange_purge_window(_at(10, 0, dt.date(2026, 11, 9)))
    assert main._in_open_protect_window(_at(9, 20, dt.date(2026, 11, 9)))


def test_backcheck_wakes_at_muhurat_open():
    assert 0 < main._unprotected_backcheck_next_sleep(_at(14, 19)) <= 61
    assert main._unprotected_backcheck_next_sleep(_at(14, 25)) == float(main._OPEN_PROTECT_EVERY_SECONDS)


def test_market_open_now(monkeypatch):
    class _F(dt.datetime):
        @classmethod
        def utcnow(cls):
            return dt.datetime(2026, 11, 8, 9, 0)  # 14:30 IST
    monkeypatch.setattr(main.dt, "datetime", _F)
    assert main._nse_equity_market_open_now()
    assert main._swing_real_entry_session_open()


def test_market_hours_between_counts_only_muhurat():
    h = main._nse_market_hours_between(_at(0, 0), _at(23, 0))
    assert abs(h - 70 / 60) < 1e-6
