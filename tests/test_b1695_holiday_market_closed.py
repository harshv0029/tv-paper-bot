"""B-1695 (2026-11-24): NSE holidays are closed for the real-order market-open gate."""
import datetime as dt
from unittest.mock import patch

import main


def _at(day, h=10, m=0):
    return dt.datetime.fromisoformat(day).replace(hour=h, minute=m)


def test_listed_holiday_is_closed():
    for day in sorted(main.NSE_HOLIDAYS_2026):
        if _at(day).weekday() < 5:
            assert main._nse_equity_calendar_open(_at(day)) is False, day


def test_normal_weekday_still_open_in_session_only():
    assert main._nse_equity_calendar_open(_at("2026-11-23")) is True
    assert main._nse_equity_calendar_open(_at("2026-11-23", 9, 0)) is False
    assert main._nse_equity_calendar_open(_at("2026-11-23", 15, 31)) is False


def test_holiday_market_open_now_false_without_live_ticks():
    fake = _at("2026-11-24", 9, 20)
    with patch.object(main, "_market_live_open", return_value=False), \
         patch.object(main.dt, "datetime", wraps=dt.datetime) as m:
        m.utcnow.return_value = fake - dt.timedelta(minutes=main.IST_OFFSET_MIN)
        assert main._nse_equity_market_open_now() is False
