"""B-1371: Render restart tracking (heartbeat + boot event in Upstash, /restart-history)."""
import json

import main


def _store():
    data = {}
    return data, (lambda k: data.get(k)), (lambda k, v: data.__setitem__(k, v))


def _reset(monkeypatch, boot_ts):
    monkeypatch.setattr(main, "_BOOT_TS", boot_ts)
    monkeypatch.setattr(main, "_RESTART_STATE", {"boot_logged": False, "last_beat": 0.0, "peak_rss_now": 0.0, "last_event": None})


def test_first_boot_logs_unknown_and_writes_heartbeat(monkeypatch):
    data, get, put = _store()
    _reset(monkeypatch, 1000.0)
    ev = main._restart_tracker_tick(now=1010.0, get=get, put=put)
    assert ev["cause_guess"] == "unknown_no_prior_heartbeat"
    assert json.loads(data[main._RESTART_HEARTBEAT_KEY])["boot_ts"] == 1000.0
    assert len(json.loads(data[main._RESTART_EVENTS_KEY])) == 1
    # later ticks never log the boot again; the heartbeat refreshes only every minute
    assert main._restart_tracker_tick(now=1030.0, get=get, put=put) is None
    assert json.loads(data[main._RESTART_HEARTBEAT_KEY])["last_alive_ts"] == 1010.0
    main._restart_tracker_tick(now=1080.0, get=get, put=put)
    assert json.loads(data[main._RESTART_HEARTBEAT_KEY])["last_alive_ts"] == 1080.0
    assert len(json.loads(data[main._RESTART_EVENTS_KEY])) == 1


def test_restart_reads_previous_heartbeat_and_guesses_cause(monkeypatch):
    data, get, put = _store()
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc")
    data[main._RESTART_HEARTBEAT_KEY] = json.dumps({"boot_ts": 100.0, "last_alive_ts": 4000.0, "commit": "abc",
                                                    "rss_now_mb": 1900.0, "loop_lag_s": 0.2})
    _reset(monkeypatch, 4100.0)
    ev = main._restart_tracker_tick(now=4110.0, get=get, put=put)
    assert ev["cause_guess"] == "oom_suspect"
    assert ev["downtime_s_max"] == 100.0 and ev["prev_uptime_min"] == 65.0


def test_cause_rules():
    assert main._restart_cause({"commit": "a"}, "b") == "deploy"
    assert main._restart_cause({"commit": "a", "loop_lag_s": 60}, "a") == "freeze_suspect"
    assert main._restart_cause({"commit": "a", "threadpool_used": 80, "threadpool_total": 80}, "a") == "freeze_suspect"
    assert main._restart_cause({"commit": "a", "rss_now_mb": 700}, "a") == "platform_or_unknown"


def test_summary_counts_and_ist():
    now = 1_793_036_322.0  # 2026-10-26 23:08 IST
    ev = [{"boot_ts": now - 60, "boot_ist": main._ist_str(now - 60), "cause_guess": "deploy", "in_market_hours": False},
          {"boot_ts": now - 30 * 86400, "boot_ist": main._ist_str(now - 30 * 86400), "cause_guess": "oom_suspect"}]
    s = main._restart_summary(ev, now=now)
    assert s == {"total": 2, "today_ist": 1, "last_7d": 1, "last_7d_in_market_hours": 0,
                 "by_cause": {"deploy": 1, "oom_suspect": 1}}
    assert main._ist_str(now).endswith("IST") and main._ist_str(now).startswith("2026-10-26 23:")
    assert main._in_nse_session(now - 12 * 3600)  # 11:08 IST Monday


def test_b1406_alarm_thread_stacks_survive_a_restart(monkeypatch):
    data, get, put = _store()
    _reset(monkeypatch, 1000.0)
    alarm = {"ts": 1005.0, "loop_lag_s": 20.8, "rss_mb": 920.0, "threadpool": "0/80", "threads": ["MainThread: a:1 > b:2"]}
    monkeypatch.setattr(main, "_WATCHDOG_STATE", {**main._WATCHDOG_STATE, "alarms": 1, "first_alarm": alarm, "last_alarm": alarm})
    main._restart_tracker_tick(now=1010.0, get=get, put=put)
    beat = json.loads(data[main._RESTART_HEARTBEAT_KEY])
    assert beat["first_alarm_threads"] == ["MainThread: a:1 > b:2"] and beat["last_alarm_threads"] == ["MainThread: a:1 > b:2"]
    _reset(monkeypatch, 2000.0)
    ev = main._restart_tracker_tick(now=2010.0, get=get, put=put)
    assert ev["prev_first_alarm_threads"] == ["MainThread: a:1 > b:2"]
