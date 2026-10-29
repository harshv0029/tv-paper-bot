"""B-1418 (live 2026-10-29): a 16 s boot stall counted as several alarms (one per 5 s check), the cause was lost at
each restart, and the stall itself was the viable-stack first-sight Upstash merge/push running on the event loop."""
import json

import main


def _fresh(monkeypatch):
    monkeypatch.setattr(main, "_WATCHDOG_STATE", {"alarms": 0, "first_alarm": None, "last_alarm": None})
    monkeypatch.setattr(main, "_WATCHDOG_IN_ALARM", {"on": False})
    main._WATCHDOG_DAY.update(day=None, n=0, hydrated=True, events=[])


def test_one_freeze_is_one_alarm_and_a_new_freeze_is_another(monkeypatch):
    _fresh(monkeypatch)
    t = 1793251712.0  # 2026-10-29 10:58 IST
    monkeypatch.setattr(main, "_loop_heartbeat_ts", t)
    for k in range(4):  # 20-35 s stale: one episode, four checks
        main._watchdog_check(now=t + 20 + 5 * k, rss_mb=500)
    assert main._watchdog_alarms_today(t) == 1 and main._WATCHDOG_STATE["alarms"] == 1
    monkeypatch.setattr(main, "_loop_heartbeat_ts", t + 100)
    assert main._watchdog_check(now=t + 101, rss_mb=500) is None  # recovered
    main._watchdog_check(now=t + 130, rss_mb=500)  # a second freeze
    assert main._watchdog_alarms_today(t) == 2


def test_alarm_reason_is_kept_and_survives_restart(monkeypatch):
    _fresh(monkeypatch)
    t = 1793251712.0
    saved = {}
    main._watchdog_day_bump(t, put=lambda k, v: saved.__setitem__(k, v),
                            info={"ts": t, "loop_lag_s": 16.0, "rss_pct": 32.5, "threadpool": "0/80",
                                  "threads": ["ThreadPoolExecutor-0_1: _pf:1", "MainThread: _load_viable_overrides:1"]})
    ev = json.loads(saved[main._WATCHDOG_DAY_KEY])["events"][0]
    assert ev["ist"] == "10:58:32 IST" and ev["loop_lag_s"] == 16.0 and ev["threads"] == ["MainThread: _load_viable_overrides:1"]
    main._WATCHDOG_DAY.update(day=None, n=0, hydrated=False, events=[])  # restart
    monkeypatch.setattr(main, "_ist_day", lambda ts=None: "2026-10-29")
    main._watchdog_day_hydrate(get=lambda k: saved[k])
    assert main._watchdog_alarms_today() == 1 and main._watchdog_alarm_events_today()[0]["ist"] == "10:58:32 IST"


def test_first_sight_stack_sync_runs_off_the_calling_thread():
    src = open(main.__file__).read()  # conftest stubs the function itself, so read its source text
    body = src[src.index("def _ensure_viable_stack_hydrated"):src.index("def _ensure_viable_stack_hydrated") + 4000]
    assert "threading.Thread(target=_first_sight" in body


def test_b1422_stacks_name_the_event_loop_thread_and_skip_uvicorn_main():
    import threading
    import main
    out = []
    t = threading.Thread(target=lambda: out.extend(main._busy_thread_stacks()))
    t.start()
    t.join()
    loop_rows = [r for r in out if "(event loop)" in r]
    assert len(loop_rows) == 1  # the main thread is always reported, with its innermost frames
    assert all("uvicorn" not in r for r in out if "(event loop)" not in r)


def test_b1422_event_keeps_loop_thread_first():
    import main
    info = {"loop_lag_s": 16.7, "rss_pct": 40, "threadpool": "0/80",
            "threads": ["ThreadPoolExecutor-2_0: _pf:1", "asyncio_0: _run_swing_scan:2", "scan-prefetch_0: x:1",
                        "MainThread (event loop): base_events.py:_run_once:1"]}
    import copy
    before = copy.deepcopy(main._WATCHDOG_DAY)
    try:
        main._watchdog_day_bump(now=1793262086.0, put=lambda k, v: None, info=info)
        ev = main._WATCHDOG_DAY["events"][-1]
    finally:
        main._WATCHDOG_DAY.clear()
        main._WATCHDOG_DAY.update(before)
    assert ev["threads"][0].startswith("MainThread (event loop)")
    assert not any(t.startswith(("ThreadPoolExecutor", "scan-prefetch")) for t in ev["threads"])
