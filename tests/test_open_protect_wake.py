import datetime as dt

import main

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(h, m, s=0, day=26):  # 2026-10-26 is a Monday
    return dt.datetime(2026, 10, day, h, m, s, tzinfo=IST)


def test_wakes_exactly_at_open():
    assert main._unprotected_backcheck_next_sleep(_t(9, 13, 20)) == 105.0


def test_far_before_open_uses_base_cadence():
    assert main._unprotected_backcheck_next_sleep(_t(8, 0)) == 300.0


def test_fast_cadence_inside_open_window():
    assert main._unprotected_backcheck_next_sleep(_t(9, 15, 5)) == 20.0
    assert main._unprotected_backcheck_next_sleep(_t(9, 29, 59)) == 20.0


def test_normal_cadence_after_window_and_weekend():
    assert main._unprotected_backcheck_next_sleep(_t(9, 30)) == 300.0
    assert main._unprotected_backcheck_next_sleep(_t(9, 14, 0, day=24)) == 300.0  # Saturday


def test_loop_uses_adaptive_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(main, "_unprotected_backcheck_once", lambda: True)
    monkeypatch.setattr(main, "_unprotected_backcheck_next_sleep", lambda: 20.0)
    main._unprotected_backcheck_loop(sleep=slept.append, rounds=2)
    assert slept == [20.0, 20.0]
