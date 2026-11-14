"""B-1575: numbered Upstash slots (_1 October DB, _2 this month's): boot picks the reachable slot with the newest
heartbeat; the probe fails over after repeated HTTP refusals and never restores from the new target."""
import json

import pytest

import main


class R:
    def __init__(self, code, result=None):
        self.status_code, self._r, self.content, self.text = code, result, b"x", ""

    def json(self):
        return {"result": self._r}


ENV = {"UPSTASH_REDIS_REST_URL_1": "http://one", "UPSTASH_REDIS_REST_TOKEN_1": "a",
       "UPSTASH_REDIS_REST_URL_2": "http://two", "UPSTASH_REDIS_REST_TOKEN_2": "b"}


def beat(ts):
    return json.dumps({"last_alive_ts": ts})


@pytest.fixture(autouse=True)
def keep_globals(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", main.UPSTASH_REDIS_REST_URL)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", main.UPSTASH_REDIS_REST_TOKEN)
    saved = dict(main._UPSTASH_SLOT_STATE)
    monkeypatch.setattr(main, "_upstash_force_full_push", lambda: None)
    yield
    main._UPSTASH_SLOT_STATE.clear()
    main._UPSTASH_SLOT_STATE.update(saved)


def test_slots_read_from_env():
    assert [n for n, _u, _t in main._upstash_slots_from_env(ENV)] == [1, 2]
    assert main._upstash_slots_from_env({"UPSTASH_REDIS_REST_URL_1": "x"}) == []


def test_boot_skips_suspended_slot():
    get = lambda url, **k: R(403) if "two" in url else R(200, None)
    assert main._upstash_select_slot_at_boot(ENV, get) == 1
    assert main.UPSTASH_REDIS_REST_URL == "http://one"


def test_boot_prefers_newest_heartbeat_then_highest_slot():
    get = lambda url, **k: R(200, beat(200)) if "one" in url else R(200, beat(100))
    assert main._upstash_select_slot_at_boot(ENV, get) == 1
    get = lambda url, **k: R(200, None)
    assert main._upstash_select_slot_at_boot(ENV, get) == 2


def test_failover_masks_target_and_switches():
    main._upstash_activate_slot(2, "http://two", "b", "test")
    assert main._upstash_failover(ENV, lambda url, **k: R(200, None)) == 1
    assert main.UPSTASH_REDIS_REST_URL == "http://one"
    assert main._UPSTASH_STALE_DB["stale"] is True
    assert main._upstash_unmask("tv_paper_bot:real_positions:v1", "[old]") is None


def test_failover_stays_when_no_other_slot_reachable():
    main._upstash_activate_slot(2, "http://two", "b", "test")
    assert main._upstash_failover(ENV, lambda url, **k: R(403)) is None
    assert main.UPSTASH_REDIS_REST_URL == "http://two"


def test_probe_fails_over_after_two_refusals(monkeypatch):
    main._upstash_activate_slot(2, "http://two", "b", "test")
    calls = []
    monkeypatch.setattr(main, "_upstash_failover", lambda: calls.append(1))
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: R(403))
    main._upstash_probe(now=1.0)
    assert calls == []
    main._upstash_probe(now=2.0)
    assert calls == [1]
