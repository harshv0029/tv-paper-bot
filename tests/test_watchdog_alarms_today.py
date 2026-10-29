"""User 2026-10-29: watchdog alarms and Render restarts are counted per IST calendar day and survive a restart."""
import json

import main


def _reset():
    main._WATCHDOG_DAY.update(day=None, n=0, hydrated=False)


def test_bump_counts_today_and_persists():
    _reset()
    saved = {}
    t = 1793247750.0  # 2026-10-29 09:52 IST
    main._watchdog_day_bump(t, put=lambda k, v: saved.__setitem__(k, v))
    main._watchdog_day_bump(t + 60, put=lambda k, v: saved.__setitem__(k, v))
    assert main._watchdog_alarms_today(t) == 2
    assert json.loads(saved[main._WATCHDOG_DAY_KEY]) == {"day": "2026-10-29", "n": 2, "events": []}


def test_new_ist_day_starts_at_zero():
    _reset()
    t = 1793247750.0
    main._watchdog_day_bump(t, put=lambda k, v: None)
    assert main._watchdog_alarms_today(t + 86400) == 0
    main._watchdog_day_bump(t + 86400, put=lambda k, v: None)
    assert main._watchdog_alarms_today(t + 86400) == 1


def test_restart_restores_todays_count(monkeypatch):
    _reset()
    today = main._ist_day()
    main._watchdog_day_hydrate(get=lambda k: json.dumps({"day": today, "n": 3}))
    assert main._watchdog_alarms_today() == 3
    _reset()
    main._watchdog_day_hydrate(get=lambda k: json.dumps({"day": "2000-01-01", "n": 9}))  # an old day is not today
    assert main._watchdog_alarms_today() == 0


def test_dashboard_uses_ist_calendar_day():
    html = open("static/trade-view4.html").read()
    assert 'toLocaleDateString("en-CA", {timeZone: "Asia/Kolkata"})' in html
    assert "watchdog alarms today" in html
