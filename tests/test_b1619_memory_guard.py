"""B-1619: wall-clock memory guard (slow ticks starved the every-20-ticks trim; 8 OOM restarts 17-Nov)."""
import main


def _reset():
    main._MEMORY_GUARD_STATE.update(last_ts=0.0, runs=0, trims=0, pressure_checks=0, last_rss_mb=None)


def test_below_trim_threshold_does_nothing():
    _reset()
    calls = []
    out = main._memory_guard_tick(now=1000.0, rss_mb=0.4 * main.RSS_LIMIT_MB,
                                  trim=lambda: calls.append("t"), pressure=lambda now_mb: calls.append("p"))
    assert out["trimmed"] is False and out["pressure"] is False and calls == []


def test_trims_between_trim_pct_and_warn():
    _reset()
    calls = []
    out = main._memory_guard_tick(now=1000.0, rss_mb=0.6 * main.RSS_LIMIT_MB,
                                  trim=lambda: calls.append("t"), pressure=lambda now_mb: calls.append("p"))
    assert out["trimmed"] is True and calls == ["t"]


def test_pressure_check_at_warn_and_rate_limited():
    _reset()
    calls = []
    kw = dict(rss_mb=0.8 * main.RSS_LIMIT_MB, trim=lambda: calls.append("t"),
              pressure=lambda now_mb: calls.append(("p", now_mb)))
    assert main._memory_guard_tick(now=1000.0, **kw)["pressure"] is True
    assert main._memory_guard_tick(now=1030.0, **kw) is None  # within 60 s
    assert main._memory_guard_tick(now=1061.0, **kw)["pressure"] is True
    assert calls == [("p", 0.8 * main.RSS_LIMIT_MB)] * 2
    assert main._MEMORY_GUARD_STATE["pressure_checks"] == 2


def test_watchdog_loop_calls_guard(monkeypatch):
    seen = []
    for name in ("_watchdog_day_hydrate", "_watchdog_check", "_upstash_probe", "_restart_tracker_tick"):
        monkeypatch.setattr(main, name, lambda *a, **k: None)
    monkeypatch.setattr(main, "_memory_guard_tick", lambda: seen.append(1))
    main._watchdog_loop(sleep=lambda s: None, rounds=2)
    assert seen == [1, 1]


def test_tick_housekeeping_has_wall_clock_floor():
    import inspect
    src = inspect.getsource(main)
    assert "_MEMORY_TICK_HOUSEKEEP_MAX_GAP_S" in src and main._MEMORY_TICK_HOUSEKEEP_MAX_GAP_S <= 600


def test_shadow_log_index_created(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "t.db"
    monkeypatch.setattr(main, "DB_PATH", str(db))
    main.init_db()
    names = {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_signal_shadow_day_tag_sym" in names
