"""B-1657: View 4 'Expected exit' always carries a time (IST), not only a date."""
import datetime as dt

import main


def _at(monkeypatch, y, mo, d, h, mi):
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(y, mo, d, h, mi))


def test_swing_strategy_row_shows_the_1500_sweep_time():
    r = main._expected_exit_for_position("swing", "gap_and_go", "2026-10-29")
    assert r["expected_exit"].endswith(" 15:00 IST") and len(r["expected_exit"]) == len("2026-10-29 15:00 IST")
    assert "15:00 IST" in r["expected_exit_basis"]


def test_immediate_row_time_follows_the_sweep_window(monkeypatch):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: dt.date.fromisoformat(str(d)[:10]).weekday() < 5)
    _at(monkeypatch, 2026, 11, 20, 11, 7)   # Fri, inside 09:20-15:10
    assert main._swing_immediate_exit_stamp() == "2026-11-20 11:07 IST"
    _at(monkeypatch, 2026, 11, 20, 8, 0)    # before the window
    assert main._swing_immediate_exit_stamp() == "2026-11-20 09:20 IST"
    _at(monkeypatch, 2026, 11, 20, 22, 0)   # after the window -> next trading day (Mon)
    assert main._swing_immediate_exit_stamp() == "2026-11-23 09:20 IST"


def test_consumers_still_read_the_date():
    ex = main._expected_exit_for_position("swing", "gap_and_go", "2026-10-29")
    dl = main._exit_timing_deadline("swing", ex)
    assert dl[0].date().isoformat() == ex["expected_exit"][:10] and dl[0].time() == main.EXIT_TIMING_SWING_DEADLINE
