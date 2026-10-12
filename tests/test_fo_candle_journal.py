"""B-860: fo_option_candles survives a simulated Render wipe via the Upstash day journal."""
import os
import tempfile
from contextlib import closing

import pytest

import fo_candle_journal as j
import main


@pytest.fixture
def remote(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    j._last_hash.clear()
    j._last_push_ts.clear()
    return store


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _bar(conn, tok, ts, px=100.0):
    conn.execute(
        "INSERT INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, kind, right, "
        "strike, expiry, bucket_start_ts, open, high, low, close, tick_count) "
        "VALUES (?, 'NIFTY25000CE', 'NIFTY', 'option', 'call', 25000, '2026-10-15', ?, ?, ?, ?, ?, 5)",
        (tok, ts, px, px + 1, px - 1, px))
    conn.commit()


def _count():
    with closing(main.get_db()) as c:
        return c.execute("SELECT COUNT(*) FROM fo_option_candles").fetchone()[0]


def test_wipe_then_restore(remote):
    _fresh_db()
    with closing(main.get_db()) as c:
        for i in range(3):
            _bar(c, "T1", 1_760_000_000 + i * 300)
    assert main.sync_fo_option_candles_external() == 1
    _fresh_db()
    assert _count() == 0
    assert main.hydrate_fo_option_candles_from_external() == 3
    assert _count() == 3
    assert main.hydrate_fo_option_candles_from_external() == 0  # idempotent


def test_wiped_local_never_shrinks_remote(remote):
    _fresh_db()
    with closing(main.get_db()) as c:
        for i in range(3):
            _bar(c, "T1", 1_760_000_000 + i * 300)
    main.sync_fo_option_candles_external()
    _fresh_db()
    j._last_hash.clear()
    j._last_push_ts.clear()
    with closing(main.get_db()) as c:
        _bar(c, "T2", 1_760_000_000)
    assert main.sync_fo_option_candles_external() == 0
    day = j.ist_day(1_760_000_000)
    assert len(j.export_day_rows(main._upstash_get, day)) == 3


def test_unchanged_day_not_repushed_and_noop_without_upstash(remote, monkeypatch):
    _fresh_db()
    with closing(main.get_db()) as c:
        _bar(c, "T1", 1_760_000_000)
    assert main.sync_fo_option_candles_external() == 1
    assert main.sync_fo_option_candles_external() == 0
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "")
    assert main.sync_fo_option_candles_external() == 0
    assert main.hydrate_fo_option_candles_from_external() == 0


def test_restore_is_newest_day_first_and_commits_per_day(remote, monkeypatch):
    _fresh_db()
    base = 1_760_000_000
    with closing(main.get_db()) as c:
        for d in range(3):
            _bar(c, f"T{d}", base + d * 86400)
    assert main.sync_fo_option_candles_external() == 3
    _fresh_db()
    order = []
    orig = j._key

    def spy(day, suffix):
        if suffix == "meta":
            order.append(day)
        return orig(day, suffix)

    monkeypatch.setattr(j, "_key", spy)
    with closing(main.get_db()) as c:
        j.restore_from_remote(c, main._upstash_get)
    assert len(order) == 3 and order == sorted(order, reverse=True)
