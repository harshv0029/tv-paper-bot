import datetime as dt
import sqlite3

import pytest

import fo_candle_journal as fj
import main


def test_lean_month_only():
    assert main._upstash_lean(dt.datetime(2026, 11, 25, 10, 0)) is True
    assert main._upstash_lean(dt.datetime(2026, 12, 1, 10, 0)) is False


def test_restart_events_exempt():
    assert main._upstash_pause_exempt("restart_tracker:events")


def test_restart_tracker_marks_boot_logged_when_events_write_refused(monkeypatch):
    monkeypatch.setattr(main, "_RESTART_STATE", dict(main._RESTART_STATE, boot_logged=False, last_beat=0.0))
    store, gets = {}, []

    def get(k):
        gets.append(k)
        return store.get(k)

    def put(k, v):
        if k == main._RESTART_EVENTS_KEY:
            raise main.UpstashPausedForDay("paused")
        store[k] = v
    main._restart_tracker_tick(now=1000.0, get=get, put=put)
    n = len(gets)
    main._restart_tracker_tick(now=1010.0, get=get, put=put)
    assert main._RESTART_STATE["boot_logged"] is True and len(gets) == n


def test_hydrate_failure_backs_off(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_GENERIC_HYDRATE_FAIL", {})
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set())
    calls = []

    def boom(conn, table):
        calls.append(table)
        raise ValueError("bad merge")
    monkeypatch.setattr(main, "_generic_hydrate_table", boom)
    t = main._GENERIC_MIRROR_UPSTASH_TABLES[0]
    main.hydrate_generic_tables_from_external(only={t})
    main.hydrate_generic_tables_from_external(only={t})
    assert calls == [t]
    f = main._GENERIC_HYDRATE_FAIL[t]
    assert f["count"] == 1 and "bad merge" in f["last_error"]
    f["next_try"] = 0.0
    main.hydrate_generic_tables_from_external(only={t})
    assert calls == [t, t] and main._GENERIC_HYDRATE_FAIL[t]["count"] == 2


def test_backoff_caps_at_30_min():
    main._GENERIC_HYDRATE_FAIL.pop("zz", None)
    for _ in range(12):
        main._generic_hydrate_note_fail("zz", "x", now=0.0)
    assert main._GENERIC_HYDRATE_FAIL.pop("zz")["next_try"] == main._GENERIC_HYDRATE_BACKOFF_MAX_SEC


def test_focandle_restore_skips_past_days_on_disk(monkeypatch):
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(fj, "local_days", lambda c: ["2026-11-20", "2026-11-23"])
    monkeypatch.setattr(fj, "_get_days", lambda get: ["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-25"])
    asked = []

    def get(k):
        asked.append(k)
        return None
    fj.restore_from_remote(conn, get, max_days=2, skip_local_past=True, today="2026-11-25")
    assert [k for k in asked if k.endswith(":meta")] == [fj._key("2026-11-25", "meta")]
    asked.clear()
    fj.restore_from_remote(conn, get, max_days=2, skip_local_past=True, today="2026-11-23")
    assert fj._key("2026-11-23", "meta") in asked  # today merges even when present locally
    asked.clear()
    fj.restore_from_remote(conn, get)
    assert len([k for k in asked if k.endswith(":meta")]) == 4  # default unchanged


def test_viable_stack_push_skips_readback_in_lean():
    import inspect
    src = inspect.getsource(main)
    assert "ok = True if _upstash_lean() else _upstash_get(_VIABLE_STACK_REDIS_KEY) == payload" in src
