import datetime as dt

import pytest

import main


def _at(monkeypatch, y, m, d):
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(y, m, d, 11, 0))
    monkeypatch.setattr(main, "_upstash_usage_totals", lambda: ({}, 0, 0))
    monkeypatch.setattr(main, "_upstash_usage_day", f"{y:04d}-{m:02d}-{d:02d}")


@pytest.mark.parametrize("day", [(2026, 11, 24), (2026, 11, 28), (2026, 11, 29), (2026, 11, 10)])
def test_closed_nov_day_refuses_non_exempt_write(monkeypatch, day):
    _at(monkeypatch, *day)
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("tv_paper_bot:tbl:fno_tape:meta")


@pytest.mark.parametrize("day", [(2026, 11, 24), (2026, 11, 28)])
def test_closed_day_keeps_real_money_writes(monkeypatch, day):
    _at(monkeypatch, *day)
    main._upstash_pause_check("tv_paper_bot:tbl:real_trades:meta")
    main._upstash_pause_check("restart_tracker:heartbeat")
    main._upstash_pause_check(main._REAL_POSITIONS_REDIS_KEY)


@pytest.mark.parametrize("day", [(2026, 11, 25), (2026, 12, 26), (2026, 12, 25)])
def test_trading_day_or_other_month_writes(monkeypatch, day):
    _at(monkeypatch, *day)
    main._upstash_pause_check("tv_paper_bot:tbl:fno_tape:meta")


def test_reads_are_not_gated(monkeypatch):
    _at(monkeypatch, 2026, 11, 24)
    assert main._upstash_closed_day_pause() is True
    import inspect
    assert "_upstash_pause_check" not in inspect.getsource(main._upstash_get)
