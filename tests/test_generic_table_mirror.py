"""Generic Upstash mirror for every remaining state table (2026-10-06, user:
"Everything on render must be attached to some memory so that no data is lost
while restart of render"). A fake in-memory Upstash replaces the REST helpers.

Run: pytest tests/test_generic_table_mirror.py -v
"""
import os
import tempfile
from contextlib import closing

import pytest

import main


@pytest.fixture
def remote(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    return store


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _insert_trade(conn, symbol="FOO.NS"):
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (1.0, ?, 'buy', 3, 10.0, 1.0, 's', '{}')", (symbol,))
    conn.commit()


def test_changed_table_is_pushed_and_restored_after_a_wipe(remote):
    _fresh_db()
    main.hydrate_generic_tables_from_external()          # nothing remote yet
    with closing(main.get_db()) as c:
        _insert_trade(c)
    assert main.sync_generic_tables_external() >= 1
    _fresh_db()                                           # simulated Render restart
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        rows = c.execute("SELECT symbol, qty FROM trades").fetchall()
    assert [(r["symbol"], r["qty"]) for r in rows] == [("FOO.NS", 3)]


def test_unchanged_table_is_not_pushed_again(remote):
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        _insert_trade(c)
    main.sync_generic_tables_external()
    assert main.sync_generic_tables_external() == 0


def test_never_overwrites_remote_before_hydrate_reached_upstash(remote, monkeypatch):
    _fresh_db()
    remote[main._generic_mirror_key("trades", "c0")] = '[{"id": 1, "ts": 1.0, "symbol": "KEEP.NS", "action": "buy", "qty": 1, "price": 1.0, "fx_to_inr": 1.0, "strategy": "s", "raw_payload": "{}"}]'
    remote[main._generic_mirror_key("trades", "meta")] = '{"chunks": 1, "rows": 1}'
    def boom(k):
        raise RuntimeError("upstash down")
    monkeypatch.setattr(main, "_upstash_get", boom)
    main.sync_generic_tables_external()                   # hydrate fails -> must not push empty
    assert "KEEP.NS" in remote[main._generic_mirror_key("trades", "c0")]


def test_kill_switch_tables_always_restore_over_the_seeded_default(remote):
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        c.execute("INSERT OR REPLACE INTO trading_control (id, enabled, updated_at, updated_by, reason) VALUES (1, 0, 1.0, 't', 'paused')")
        c.commit()
    main.sync_generic_tables_external()
    _fresh_db()                                           # fresh DB: no row == trading enabled
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert c.execute("SELECT enabled FROM trading_control WHERE id = 1").fetchone()[0] == 0


def test_large_table_is_chunked_and_restored(remote, monkeypatch):
    monkeypatch.setattr(main, "_GENERIC_MIRROR_CHUNK_CHARS", 200)
    _fresh_db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        for i in range(10):
            _insert_trade(c, f"S{i}.NS")
    main.sync_generic_tables_external()
    assert main._generic_mirror_key("trades", "c1") in remote
    _fresh_db()
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 10
