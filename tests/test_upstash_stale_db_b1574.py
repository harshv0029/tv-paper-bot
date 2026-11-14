"""B-1574: pointing the bot at an old Upstash database (early-October snapshot) must not restore weeks-old state."""
import json

import pytest

import main

DAY = 86400.0


@pytest.fixture
def fresh_check(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    main._UPSTASH_STALE_DB.update(checked=False, stale=False, reason=None, heartbeat_age_days=None, at=None)
    main._upstash_written_keys.clear()


def test_old_heartbeat_is_stale(fresh_check):
    now = 1_800_000_000.0
    store = {main._RESTART_HEARTBEAT_KEY: json.dumps({"last_alive_ts": now - 40 * DAY})}
    assert main._upstash_db_is_stale(now=now, raw_get=store.get) is True
    assert main._UPSTASH_STALE_DB["heartbeat_age_days"] == 40.0


def test_recent_heartbeat_is_fresh(fresh_check):
    now = 1_800_000_000.0
    store = {main._RESTART_HEARTBEAT_KEY: json.dumps({"last_alive_ts": now - 2 * DAY})}
    assert main._upstash_db_is_stale(now=now, raw_get=store.get) is False


def test_data_without_heartbeat_is_stale_but_empty_db_is_not(fresh_check):
    assert main._upstash_db_is_stale(raw_get={main._REAL_POSITIONS_REDIS_KEY: "[{}]"}.get) is True
    main._UPSTASH_STALE_DB["checked"] = False
    assert main._upstash_db_is_stale(raw_get={}.get) is False


def test_check_failure_is_retried_not_cached(fresh_check):
    def boom(k):
        raise RuntimeError("down")
    assert main._upstash_db_is_stale(raw_get=boom) is False
    assert main._UPSTASH_STALE_DB["checked"] is False


def test_stale_db_reads_are_masked_until_written(fresh_check, monkeypatch):
    main._UPSTASH_STALE_DB.update(checked=True, stale=True)
    assert main._upstash_unmask("tv_paper_bot:tbl:positions:v1:meta", '{"rows":5}') is None
    main._upstash_set_url("tv_paper_bot:tbl:positions:v1:meta")
    assert main._upstash_unmask("tv_paper_bot:tbl:positions:v1:meta", '{"rows":5}') == '{"rows":5}'


def test_stale_db_real_positions_hydrate_restores_nothing(fresh_check, monkeypatch):
    main._UPSTASH_STALE_DB.update(checked=True, stale=True)

    class R:
        content = b"x"

        def raise_for_status(self):
            pass

        def json(self):
            return {"result": json.dumps([{"symbol": "OLD.NS", "qty": 5}])}
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: R())
    seen = []
    monkeypatch.setattr(main, "json", main.json)
    orig_loads = main.json.loads
    monkeypatch.setattr(main.json, "loads", lambda s, *a, **k: seen.append(s) or orig_loads(s, *a, **k))
    main.hydrate_real_positions_from_external()
    assert not any("OLD.NS" in str(s) for s in seen)


def test_fresh_db_reads_pass_through(fresh_check):
    main._UPSTASH_STALE_DB.update(checked=True, stale=False)
    assert main._upstash_unmask("k", "v") == "v"
