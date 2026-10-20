import datetime as dt
import main


def test_holidays_not_trading_days():
    for d in ("2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25"):
        assert not main.is_nse_trading_day(d)


def test_normal_weekday_trades():
    assert main.is_nse_trading_day("2026-10-21")
    assert main.is_nse_trading_day(dt.date(2026, 10, 21))


def test_weekend_and_muhurat_sunday_not_normal_day():
    assert not main.is_nse_trading_day("2026-10-24")
    assert not main.is_nse_trading_day("2026-11-08")


def test_fails_open_on_error():
    assert main.is_nse_trading_day("garbage")
    assert main.is_nse_trading_day(12345)


def test_swing_scan_skips_on_holiday(monkeypatch):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: False)
    called = []
    monkeypatch.setattr(main, "_run_swing_scan_pass", lambda c: called.append(1))
    monkeypatch.setattr(main, "_restore_strategy_scan_counts", lambda c: None)
    assert main._run_swing_scan(object()) is None
    assert not called
