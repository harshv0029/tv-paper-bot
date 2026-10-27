"""B-1302: tiered generic Upstash mirror (T1 safety-critical first) and a loud /health
alarm when the mirror itself gets 401/403 from Upstash. Fake in-memory Upstash, no network.

Run: pytest tests/test_b1302_mirror_tiers.py -v
"""
import os
import tempfile
from contextlib import closing

import pytest
import requests

import main


@pytest.fixture
def remote(monkeypatch):
    store = {}
    order = []
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))

    def _set(k, v):
        order.append(k)
        store[k] = v
    monkeypatch.setattr(main, "_upstash_set", _set)
    monkeypatch.setattr(main, "hydrate_git_tier_tables", lambda: 0)
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    main._generic_mirror_last_push_ts.clear()
    main._generic_hydrate_last_try.clear()
    main._GENERIC_MIRROR_AUTH_ALARM.update(active=False, status=None, table=None, op=None, at=None,
                                           count=0, error=None)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    return store, order


def _table_of(key):
    return key.split(":")[2]


def test_t1_tables_listed_first_and_all_upstash_tier():
    t = main._GENERIC_MIRROR_UPSTASH_TABLES
    n1 = len([x for x in t if x in main._GENERIC_MIRROR_T1])
    assert n1 >= 5
    assert all(x in main._GENERIC_MIRROR_T1 for x in t[:n1])
    assert not any(x in main._GENERIC_MIRROR_T1 for x in t[n1:])
    assert "trading_control" in t[:n1] and "real_trading_control" in t[:n1] and "positions" in t[:n1]
    assert t.index("trades") > t.index("positions")
    assert set(t) == {x for x in main._GENERIC_MIRROR_TABLES if x not in main._GENERIC_MIRROR_GIT_TIER}


def test_push_order_is_t1_before_t2_t3(remote):
    store, order = remote
    main.hydrate_generic_tables_from_external()
    assert main.sync_generic_tables_external() > 0
    tables = []
    for k in order:
        tb = _table_of(k)
        if tb not in tables:
            tables.append(tb)
    t1_pos = [i for i, tb in enumerate(tables) if tb in main._GENERIC_MIRROR_T1]
    other_pos = [i for i, tb in enumerate(tables) if tb not in main._GENERIC_MIRROR_T1]
    assert t1_pos and other_pos
    assert max(t1_pos) < min(other_pos)


def test_403_on_push_sets_health_alarm_and_good_push_clears_it(remote, monkeypatch):
    store, order = remote
    main.hydrate_generic_tables_from_external()

    def _forbidden(k, v):
        resp = requests.Response()
        resp.status_code = 403
        raise requests.exceptions.HTTPError("403 Forbidden", response=resp)
    monkeypatch.setattr(main, "_upstash_set", _forbidden)
    main.sync_generic_tables_external()
    a = main._GENERIC_MIRROR_AUTH_ALARM
    assert a["active"] is True and a["status"] == 403 and a["op"] == "push"
    assert a["count"] >= 1 and a["table"] in main._GENERIC_MIRROR_UPSTASH_TABLES

    import asyncio
    h = asyncio.run(main.health())
    assert h["mirror_auth_alarm"] is True
    assert h["mirror_auth_alarm_detail"]["status"] == 403

    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    main.sync_generic_tables_external()
    assert main._GENERIC_MIRROR_AUTH_ALARM["active"] is False


def test_403_on_restore_sets_alarm(remote, monkeypatch):
    def _forbidden(k):
        resp = requests.Response()
        resp.status_code = 403
        raise requests.exceptions.HTTPError("403 Forbidden", response=resp)
    monkeypatch.setattr(main, "_upstash_get", _forbidden)
    main.hydrate_generic_tables_from_external()
    a = main._GENERIC_MIRROR_AUTH_ALARM
    assert a["active"] is True and a["op"] == "restore" and a["table"] == main._GENERIC_MIRROR_UPSTASH_TABLES[0]


def test_non_auth_error_does_not_raise_alarm(remote, monkeypatch):
    main.hydrate_generic_tables_from_external()
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: (_ for _ in ()).throw(RuntimeError("boom")))
    main.sync_generic_tables_external()
    assert main._GENERIC_MIRROR_AUTH_ALARM["active"] is False


def test_simulated_wipe_restores_t1_table(remote, monkeypatch):
    store, order = remote
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        c.execute("INSERT OR REPLACE INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
                  "VALUES (1, 0, 1.0, 't', 'paused-b1302')")
        c.commit()
    main.sync_generic_tables_external()
    fd, path = tempfile.mkstemp(suffix=".db")  # simulated Render restart: fresh, re-seeded DB
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        row = c.execute("SELECT enabled, reason FROM real_trading_control WHERE id=1").fetchone()
    assert row["enabled"] == 0 and row["reason"] == "paused-b1302"
