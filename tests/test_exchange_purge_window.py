import datetime as dt
import main

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(d, h, m):
    return dt.datetime(2026, 10, d, h, m, tzinfo=IST)  # 7 Oct 2026 = Wednesday


def test_open_hours_not_purge():
    assert main._exchange_purge_window(_t(7, 9, 15)) is False
    assert main._exchange_purge_window(_t(7, 15, 14)) is False


def test_after_1515_and_before_open_is_purge():
    assert main._exchange_purge_window(_t(7, 15, 15)) is True
    assert main._exchange_purge_window(_t(7, 20, 0)) is True
    assert main._exchange_purge_window(_t(8, 9, 14)) is True


def test_weekend_is_purge():
    assert main._exchange_purge_window(_t(10, 11, 0)) is True  # Saturday
