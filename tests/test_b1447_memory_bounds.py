"""B-1447: every long-lived cache that grew over a multi-day uptime is bounded, and the fo-candle journal no longer
re-materialises every unchanged past day on each 5-min sync (the native-heap churn behind the RSS ratchet)."""
import os
import tempfile
import time
from contextlib import closing

import pandas as pd
import pytest

import data_fetch
import fo_candle_journal as j
import kotak_real_orders
import main

BASE = 1_760_000_000  # a fixed epoch; days below are BASE + d * 86400


@pytest.fixture
def remote(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        d.clear()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    yield store
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        d.clear()


def _bar(tok, ts, px=100.0):
    with closing(main.get_db()) as c:
        c.execute(
            "INSERT INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, kind, right, "
            "strike, expiry, bucket_start_ts, open, high, low, close, tick_count) "
            "VALUES (?, 'NIFTY25000CE', 'NIFTY', 'option', 'call', 25000, '2026-10-15', ?, ?, ?, ?, ?, 5)",
            (tok, ts, px, px + 1, px - 1, px))
        c.commit()


def _count_builds(monkeypatch):
    calls = []
    orig = j._day_bounds

    def spy(day):
        calls.append(day)
        return orig(day)

    monkeypatch.setattr(j, "_day_bounds", spy)
    return calls


def test_unchanged_past_days_are_not_rebuilt(remote, monkeypatch):
    for d in range(4):
        for i in range(3):
            _bar(f"T{d}", BASE + d * 86400 + i * 300)
    assert main.sync_fo_option_candles_external() == 4
    builds = _count_builds(monkeypatch)
    assert main.sync_fo_option_candles_external() == 0
    assert builds == []  # no day was re-read / re-serialised
    _bar("T9", BASE + 2 * 86400 + 7 * 300)  # one past day changes
    assert main.sync_fo_option_candles_external() == 1
    assert builds == [j.ist_day(BASE + 2 * 86400)]
    day = j.ist_day(BASE + 2 * 86400)
    assert len(j.export_day_rows(main._upstash_get, day)) == 4


def test_remote_has_more_is_checked_once_until_local_changes(remote, monkeypatch):
    for i in range(3):
        _bar("T1", BASE + i * 300)
    main.sync_fo_option_candles_external()
    # simulated wipe: fresh DB, fresh process memory, fewer local rows than remote
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        d.clear()
    _bar("T2", BASE)
    builds = _count_builds(monkeypatch)
    assert main.sync_fo_option_candles_external() == 0
    assert main.sync_fo_option_candles_external() == 0
    assert len(builds) == 1  # second pass skipped by fingerprint
    assert len(j.export_day_rows(main._upstash_get, j.ist_day(BASE))) == 3  # never shrunk


def test_day_fingerprints_match_ist_day_and_state_is_bounded(remote):
    for d in range(3):
        _bar(f"T{d}", BASE + d * 86400 + 123.5)
    with closing(main.get_db()) as c:
        fps = j.local_day_fingerprints(c)
        days = j.local_days(c)
    assert sorted(fps) == days == sorted({j.ist_day(BASE + d * 86400 + 123.5) for d in range(3)})
    assert all(v[0] == 1 for v in fps.values())
    j._last_hash["2001-01-01"] = "x"
    j._last_push_ts["2001-01-01"] = 1.0
    j._last_fp["2001-01-01"] = ("", 1, 1)
    main.sync_fo_option_candles_external()
    for d in (j._last_hash, j._last_push_ts, j._last_fp):
        assert "2001-01-01" not in d
        assert {k[0] if isinstance(k, tuple) else k for k in d} <= set(days)  # B-1568 (day, "chunks") keys


def test_scheduler_derivative_rows_are_pruned(monkeypatch):
    res, visits, counts = {}, {}, {}
    monkeypatch.setattr(main, "_scheduler_last_results", res)
    monkeypatch.setattr(main, "_scheduler_last_visit_strategies", visits)
    monkeypatch.setattr(main, "_scheduler_check_counts", counts)
    now = time.time()
    old = now - main._DERIV_RESULT_MAX_AGE_S - 60
    res.update({
        "RELIANCE.NS": {"checked_at_utc": old, "status": "checked"},       # equity: never aged out
        "NIFTY:OPT": {"checked_at_utc": old, "status": "checked"},         # underlying key: kept
        "NIFTY25000CE:STRIKE": {"checked_at_utc": old, "status": "checked"},
        "NIFTY25100CE:STRIKE": {"checked_at_utc": now, "status": "checked"},
    })
    visits.update({"RELIANCE.NS": 3, "NIFTY25000CE:STRIKE": 0, "NIFTY25100CE:STRIKE": 0,
                   "BANKNIFTY50000PE:RSI2FO": 0, "X:RSI2FO": 0})
    counts["X:RSI2FO"] = 1  # checked today: kept
    main._prune_unbounded_scheduler_state(now)
    assert set(res) == {"RELIANCE.NS", "NIFTY:OPT", "NIFTY25100CE:STRIKE"}
    assert set(visits) == {"RELIANCE.NS", "NIFTY25100CE:STRIKE", "X:RSI2FO"}


def test_scheduler_results_hard_cap(monkeypatch):
    res = {}
    monkeypatch.setattr(main, "_scheduler_last_results", res)
    monkeypatch.setattr(main, "_scheduler_last_visit_strategies", {})
    monkeypatch.setattr(main, "_SCHEDULER_RESULTS_MAX", 50)
    now = time.time()
    for i in range(200):
        res[f"OPT{i}:STRIKE"] = {"checked_at_utc": now - 1000 + i}
    res["SBIN.NS"] = {"checked_at_utc": now - 5000}
    main._prune_unbounded_scheduler_state(now)
    assert len(res) == 50
    assert "SBIN.NS" in res and "OPT199:STRIKE" in res and "OPT0:STRIKE" not in res


def test_order_reasons_capped(monkeypatch):
    monkeypatch.setattr(kotak_real_orders, "_ORDER_REASONS", {})
    monkeypatch.setattr(kotak_real_orders, "_ORDER_REASONS_MAX", 10)
    for i in range(25):
        kotak_real_orders._note_rejected({"rejected_order_id": i}, f"r{i}")
    assert len(kotak_real_orders._ORDER_REASONS) == 10
    assert kotak_real_orders.order_reason(24) == "r24" and kotak_real_orders.order_reason(0) is None


def test_data_cache_stays_at_cap(monkeypatch):
    df = pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=3), "Open": [1.0] * 3, "High": [1.0] * 3,
                       "Low": [1.0] * 3, "Close": [1.0] * 3, "Volume": [1] * 3}).set_index("Date")
    monkeypatch.setattr(data_fetch.yf, "download", lambda *a, **k: df.copy())
    monkeypatch.setattr(data_fetch, "_MAX_CACHE_ENTRIES", 5)
    monkeypatch.setattr(data_fetch, "_DATA_CACHE", {})
    for i in range(30):
        data_fetch.fetch_ohlc(f"S{i}.NS", "5d", "1d")
    assert len(data_fetch._DATA_CACHE) <= 5


def test_trim_and_cache_sizes_never_raise():
    assert main._trim_native_heap() in (True, False)
    sizes = main._bounded_cache_sizes()
    assert "scheduler_last_results" in sizes and "data_cache_entries" in sizes
    assert "fo_candle_journal._last_fp" in sizes


def test_memory_pressure_trim_uses_native_trim(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_trim_native_heap", lambda: calls.append(1) or True)
    monkeypatch.setitem(main._MEMORY_STATE, "last_trim_ts", None)
    out = main._memory_pressure_check(now_mb=main.RSS_LIMIT_MB * 0.9, trim=True)
    assert out["memory_level"] == "alarm" and calls == [1]
