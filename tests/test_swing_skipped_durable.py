"""B-1376: _swing_skipped_today survives a restart via its Upstash key; an earlier IST day's map is ignored."""
import datetime as dt
import json

import main


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value):
        self.kv[key] = value


def _setup(monkeypatch, day="2026-10-27"):
    r = _FakeRedis()
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "tok")
    monkeypatch.setattr(main, "_upstash_get", r.get)
    monkeypatch.setattr(main, "_upstash_set", r.set)
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime.fromisoformat(day + "T10:00:00"))
    # run the coalescing writer synchronously so the test is deterministic
    monkeypatch.setattr(main, "_swing_skipped_schedule_push", main._swing_skipped_push)
    monkeypatch.setattr(main, "_swing_skipped_today", {"day": "", "syms": {}})
    return r


def test_wipe_restores_today(monkeypatch):
    r = _setup(monkeypatch)
    main._note_swing_skipped("ABC.NS", "daily fetch failed")
    main._note_swing_skipped("XYZ.NS", "under 50 daily bars")
    stored = json.loads(r.kv[main._SWING_SKIPPED_REDIS_KEY])
    assert stored == {"day": "2026-10-27", "syms": {"ABC.NS": "daily fetch failed", "XYZ.NS": "under 50 daily bars"}}
    # simulated Render restart: in-memory state blank
    monkeypatch.setattr(main, "_swing_skipped_today", {"day": "", "syms": {}})
    assert main.hydrate_swing_skipped_from_external() == 2
    assert main._swing_skipped_today == {"day": "2026-10-27",
                                         "syms": {"ABC.NS": "daily fetch failed", "XYZ.NS": "under 50 daily bars"}}


def test_previous_day_ignored(monkeypatch):
    r = _setup(monkeypatch)
    r.kv[main._SWING_SKIPPED_REDIS_KEY] = json.dumps({"day": "2026-10-26", "syms": {"OLD.NS": "daily fetch failed"}})
    assert main.hydrate_swing_skipped_from_external() == 0
    assert main._swing_skipped_today == {"day": "", "syms": {}}


def test_restore_merges_with_live_notes(monkeypatch):
    r = _setup(monkeypatch)
    r.kv[main._SWING_SKIPPED_REDIS_KEY] = json.dumps({"day": "2026-10-27", "syms": {"A.NS": "x", "B.NS": "y"}})
    monkeypatch.setattr(main, "_swing_skipped_today", {"day": "2026-10-27", "syms": {"B.NS": "newer"}})
    assert main.hydrate_swing_skipped_from_external() == 1
    assert main._swing_skipped_today["syms"] == {"A.NS": "x", "B.NS": "newer"}


def test_redis_failure_never_raises(monkeypatch):
    _setup(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("upstash down")
    monkeypatch.setattr(main, "_upstash_set", boom)
    monkeypatch.setattr(main, "_upstash_get", boom)
    main._note_swing_skipped("ABC.NS", "daily fetch failed")
    assert main._swing_skipped_today["syms"] == {"ABC.NS": "daily fetch failed"}
    assert main.hydrate_swing_skipped_from_external() == 0


def test_no_upstash_no_thread(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "")
    monkeypatch.setattr(main, "_swing_skipped_today", {"day": "", "syms": {}})
    main._note_swing_skipped("ABC.NS", "daily fetch failed")
    assert main._swing_skipped_push_state["running"] is False
    assert main.hydrate_swing_skipped_from_external() == 0
