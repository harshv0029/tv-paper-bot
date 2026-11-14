"""B-1568: Upstash mirrors send only changed row-chunks, restore both formats, and do not re-push what was restored."""
import json
import os
import tempfile
from contextlib import closing

import pytest

import fo_candle_journal as j
import main


@pytest.fixture
def remote(monkeypatch):
    store, sets = {}, []

    def _set(k, v):
        sets.append(k)
        store[k] = v
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", _set)
    monkeypatch.setattr(main, "_generic_mirror_last_hash", {})
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set())
    monkeypatch.setattr(main, "_generic_mirror_last_push_ts", {})
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        d.clear()
    return store, sets


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _add_events(n, start=0):
    with closing(main.get_db()) as c:
        for i in range(start, start + n):
            c.execute("INSERT INTO real_order_events (ts, symbol, event, detail) VALUES (?,?,?,?)",
                      (1_790_000_000 + i, f"S{i}", "placed", "x" * 50))
        c.commit()


TABLE = "positions"


def _add_positions(n, start=0):
    with closing(main.get_db()) as c:
        info = c.execute(f"PRAGMA table_info({TABLE})").fetchall()
        for i in range(start, start + n):
            row = {}
            for col in info:
                name, typ, notnull, dflt, pk = col[1], (col[2] or "").upper(), col[3], col[4], col[5]
                if pk:
                    continue
                if name == "symbol":
                    row[name] = f"S{i}.NS"
                elif notnull and dflt is None:
                    row[name] = 1 if ("INT" in typ or "REAL" in typ) else "x"
            c.execute(f"INSERT INTO {TABLE} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                      tuple(row.values()))
        c.commit()


def test_append_sends_only_tail_chunk_and_restores(remote):
    store, sets = remote
    _fresh_db()
    main._generic_mirror_hydrated.add(TABLE)
    _add_positions(250)
    assert main.sync_generic_tables_external(only={TABLE}) == 1
    first = [k for k in sets if ":r" in k.split(TABLE)[-1]]
    assert len(first) == 3  # 100 + 100 + 50 rows
    sets.clear()
    _add_positions(1, start=250)
    assert main.sync_generic_tables_external(only={TABLE}) == 1
    chunk_sets = [k for k in sets if not k.endswith(":meta")]
    assert chunk_sets == [main._generic_mirror_key(TABLE, "r2")]
    meta = json.loads(store[main._generic_mirror_key(TABLE, "meta")])
    assert meta["format"] == "rowchunks" and meta["rows"] == 251
    # wipe -> restore all 251 rows, then the next sync pushes nothing new
    _fresh_db()
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    with closing(main.get_db()) as c:
        assert main._generic_hydrate_table(c, TABLE) is True
        assert c.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] == 251
    main._generic_mirror_hydrated.add(TABLE)
    sets.clear()
    main.sync_generic_tables_external(only={TABLE})
    assert [k for k in sets if not k.endswith(":meta")] == []


def test_old_format_remote_still_restores(remote):
    store, _ = remote
    _fresh_db()
    _add_positions(1)
    with closing(main.get_db()) as c:
        rows = [dict(r) for r in c.execute(f"SELECT * FROM {TABLE}").fetchall()]
    rows[0]["symbol"] = "OLD.NS"
    _fresh_db()
    payload = json.dumps(rows)
    store[main._generic_mirror_key(TABLE, "c0")] = payload[:5]
    store[main._generic_mirror_key(TABLE, "c1")] = payload[5:]
    store[main._generic_mirror_key(TABLE, "meta")] = json.dumps({"chunks": 2, "rows": 1})
    with closing(main.get_db()) as c:
        assert main._generic_hydrate_table(c, TABLE) is True
        assert c.execute(f"SELECT symbol FROM {TABLE}").fetchone()[0] == "OLD.NS"


def _bar(conn, tok, ts):
    conn.execute(
        "INSERT INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, kind, right, "
        "strike, expiry, bucket_start_ts, open, high, low, close, tick_count) "
        "VALUES (?, 'N', 'NIFTY', 'option', 'call', 25000, '2026-10-15', ?, 1, 1, 1, 1, 5)", (tok, ts))


def test_candles_send_only_changed_chunks_and_skip_after_restore(remote, monkeypatch):
    store, sets = remote
    monkeypatch.setattr(j, "ROWS_PER_CHUNK", 10)
    monkeypatch.setattr(j, "CURRENT_DAY_MIN_PUSH_SECONDS", 0)
    _fresh_db()
    base = 1_760_000_000
    with closing(main.get_db()) as c:
        for i in range(25):
            _bar(c, f"T{i}", base + i)
        c.commit()
    assert j.sync_to_remote(main.get_db(), main._upstash_get, main._upstash_set, now=base + 999_999) == 1
    day = j.ist_day(base)
    assert sum(1 for k in sets if ":r" in k) == 3
    sets.clear()
    with closing(main.get_db()) as c:
        _bar(c, "T99", base + 100)
        c.commit()
    assert j.sync_to_remote(main.get_db(), main._upstash_get, main._upstash_set, now=base + 999_999) == 1
    assert [k for k in sets if ":r" in k] == [j._key(day, "r2")]
    assert len(j.export_day_rows(main._upstash_get, day)) == 26
    # wipe + restore: nothing re-sent afterwards
    _fresh_db()
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        d.clear()
    with closing(main.get_db()) as c:
        assert j.restore_from_remote(c, main._upstash_get) == 26
    sets.clear()
    j.sync_to_remote(main.get_db(), main._upstash_get, main._upstash_set, now=base + 999_999)
    assert [k for k in sets if ":r" in k] == []


def test_restart_history_reads_upstash_once(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: calls.append(k) or json.dumps([{"boot_ts": 1}]))
    monkeypatch.setattr(main, "_RESTART_EVENTS_CACHE", {"ts": 0.0, "events": None})
    for _ in range(5):
        assert main.restart_history()["summary"]["total"] == 1
    assert calls.count(main._RESTART_EVENTS_KEY) == 1
