import asyncio
"""B-1356: a freeze or memory spike must name the code that was running, in the log, before Render kills the bot."""
from unittest.mock import patch

import main


def test_quiet_when_loop_alive_and_memory_ok(monkeypatch):
    monkeypatch.setattr(main, "_loop_heartbeat_ts", 1000.0)
    assert main._watchdog_check(now=1002.0, rss_mb=500) is None


def test_alarm_on_stale_loop_heartbeat(monkeypatch, capsys):
    monkeypatch.setattr(main, "_loop_heartbeat_ts", 1000.0)
    info = main._watchdog_check(now=1030.0, rss_mb=500)
    assert info["loop_lag_s"] == 30.0 and isinstance(info["threads"], list)
    assert "[watchdog] ALARM" in capsys.readouterr().out


def test_memory_alarm_trims_cache(monkeypatch):
    monkeypatch.setattr(main, "_loop_heartbeat_ts", 1000.0)
    with patch.object(main, "_memory_pressure_check") as trim:
        info = main._watchdog_check(now=1001.0, rss_mb=main.RSS_LIMIT_MB * 0.8)
    assert info is not None
    trim.assert_called_once()


def test_loop_never_raises():
    with patch.object(main, "_watchdog_check", side_effect=RuntimeError("x")):
        main._watchdog_loop(sleep=lambda s: None, rounds=2)


def test_health_shows_loop_lag():
    h = asyncio.run(main.health())
    assert "loop_lag_s" in h and "watchdog_alarms" in h


def test_background_threads_start_once_per_process():
    import inspect
    src = inspect.getsource(main)
    assert "_BACKGROUND_THREADS_STARTED" in src


def test_health_keeps_first_and_last_alarm(monkeypatch):
    """B-1361: /health carries the first and latest alarm (with thread stacks), since Render logs are unreadable here."""
    monkeypatch.setattr(main, "_WATCHDOG_STATE", {"alarms": 0, "first_alarm": None, "last_alarm": None})
    monkeypatch.setattr(main, "_loop_heartbeat_ts", 1000.0)
    main._watchdog_check(now=1020.0, rss_mb=500)
    main._watchdog_check(now=1040.0, rss_mb=500)
    h = asyncio.run(main.health())
    assert h["watchdog_alarms"] == 2
    assert h["watchdog_first_alarm"]["loop_lag_s"] == 20.0 and h["watchdog_last_alarm"]["loop_lag_s"] == 40.0
    assert isinstance(h["watchdog_first_alarm"]["threads"], list)
