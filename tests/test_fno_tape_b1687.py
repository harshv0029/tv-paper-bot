"""B-1687 (b) View 6 tape: one row per IST minute in 09:15-15:30 of an NSE day, compact payload, SQLite + per-minute
Upstash key (EX 3 days), restore-on-wipe via /fno-tape?fill=1, prune, never raises, journal workflow. No network."""
import datetime as dt
import json
import os
import pathlib
import sqlite3
import tempfile

import pytest

import main

MON = dt.datetime(2026, 11, 23, 10, 0)


def _r(u, k, ot, n, pc, px):
    r = {"underlying": u, "strikePrice": k, "optionType": "Call" if ot == "CE" else "Put", "expiryDate": "27-Nov-2026",
         "lastPrice": px, "pChange": pc, "numberOfContractsTraded": n, "openInterest": 1000, "changeinOpenInterest": 50,
         "impliedVolatility": 14.2, "underlyingValue": 25510.4}
    r["contract"] = main._fno_label(r)
    return r


GROUPS = main._fno_group_by_index([_r("NIFTY", 25500, "CE", 900, 12.0, 100.0),
                                   _r("BANKNIFTY", 52000, "PE", 500, 30.0, 200.0)], 50)


class FakeUpstash:
    def __init__(self):
        self.kv, self.urls = {}, []

    def post(self, url, headers=None, data=None, timeout=None):
        self.urls.append(url)
        key = url.split("/set/", 1)[1].split("?", 1)[0]
        self.kv[key] = data.decode("utf-8")

        class R:
            def raise_for_status(self):
                return None
        return R()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    monkeypatch.setattr(main, "_FNO_TAPE_STATE", {"last_minute": None, "rows_today": 0, "day": None, "upstash_ok": 0,
                                                  "upstash_fail": 0, "skipped_budget": 0, "last_error": None})
    fake = FakeUpstash()
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "tok")
    monkeypatch.setattr(main.requests, "post", fake.post)
    monkeypatch.setattr(main, "_upstash_get", lambda k: fake.kv.get(k))
    monkeypatch.setattr(main, "_upstash_budget_level", lambda: 0)
    monkeypatch.setattr(main, "_upstash_pause_check", lambda k: None)
    monkeypatch.setattr(main, "_upstash_db_is_stale", lambda *a, **k: False)
    monkeypatch.setattr(main, "_upstash_meter", lambda *a, **k: None)
    yield fake
    os.remove(path)


def test_window():
    assert main._fno_tape_window(MON)
    assert main._fno_tape_window(MON.replace(hour=9, minute=15))
    assert main._fno_tape_window(MON.replace(hour=15, minute=30))
    assert not main._fno_tape_window(MON.replace(hour=9, minute=14))
    assert not main._fno_tape_window(MON.replace(hour=15, minute=31))
    assert not main._fno_tape_window(dt.datetime(2026, 11, 22, 10, 0))  # Sunday


def test_one_row_per_minute_and_upstash_key(env):
    assert main._fno_tape_record(GROUPS, {"NIFTY": 0.4}, now=MON)
    assert not main._fno_tape_record(GROUPS, {"NIFTY": 0.5}, now=MON.replace(second=40))  # same minute
    assert main._fno_tape_record(GROUPS, {"NIFTY": 0.5}, now=MON.replace(minute=1))
    out = main._fno_tape_export("2026-11-23")
    assert out["minutes"] == 2 and out["local"] == 2
    t0 = out["tape"][0]
    assert t0["minute"] == "10:00" and t0["index_pct"] == {"NIFTY": 0.4}
    row = t0["rows"]["NIFTY"][0]
    assert dict(zip(t0["cols"], row))["lastPrice"] == 100.0 and row[0] == "NIFTY 25500 CE 27-Nov-2026"
    assert set(env.kv) == {"fno_tape_v1:2026-11-23:1000", "fno_tape_v1:2026-11-23:1001"}
    assert all(u.endswith(f"?EX={main.FNO_TAPE_UPSTASH_EX_S}") for u in env.urls)


def test_outside_window_records_nothing(env):
    assert not main._fno_tape_record(GROUPS, {}, now=MON.replace(hour=16))
    assert main._fno_tape_export("2026-11-23")["minutes"] == 0 and not env.kv


def test_restore_on_wipe_fill_from_upstash(env):
    for m in range(3):
        main._fno_tape_record(GROUPS, {}, now=MON.replace(minute=m))
    os.remove(main.DB_PATH)  # Render wipe
    sqlite3.connect(main.DB_PATH).close()
    assert main._fno_tape_export("2026-11-23")["minutes"] == 0
    out = main._fno_tape_export("2026-11-23", fill=True)
    assert out["minutes"] == 3 and out["filled_from_upstash"] == 3 and out["local"] == 0
    assert [t["minute"] for t in out["tape"]] == ["10:00", "10:01", "10:02"]


def test_budget_spent_skips_upstash_keeps_sqlite(env, monkeypatch):
    monkeypatch.setattr(main, "_upstash_budget_level", lambda: 2)
    assert main._fno_tape_record(GROUPS, {}, now=MON)
    assert not env.kv and main._FNO_TAPE_STATE["skipped_budget"] == 1
    assert main._fno_tape_export("2026-11-23")["minutes"] == 1


def test_upstash_failure_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(main.requests, "post", boom)
    assert main._fno_tape_record(GROUPS, {}, now=MON)
    assert main._FNO_TAPE_STATE["upstash_fail"] == 1 and "down" in main._FNO_TAPE_STATE["last_error"]


def test_bad_input_never_raises():
    assert main._fno_tape_record({"NIFTY": None}, None, now=MON) in (True, False)
    assert main._fno_tape_record(object(), {}, now=MON.replace(minute=5)) is False


def test_prune_older_than_keep_days(env):
    main._fno_tape_record(GROUPS, {}, now=dt.datetime(2026, 11, 18, 10, 0))
    main._fno_tape_record(GROUPS, {}, now=MON)
    assert main._fno_tape_export("2026-11-18")["minutes"] == 0
    assert main._fno_tape_export("2026-11-23")["minutes"] == 1


def test_per_index_cap():
    many = main._fno_group_by_index([_r("NIFTY", 20000 + 50 * i, "CE", 1000 - i, 1.0, 10.0) for i in range(30)], 50)
    p = main._fno_tape_payload(many, {})
    assert len(p["rows"]["NIFTY"]) == main.FNO_TAPE_PER_INDEX
    assert len(json.dumps(p)) < 3000


def test_route(env):
    main._fno_tape_record(GROUPS, {}, now=MON)
    assert main.fno_tape(date="bad")["error"]
    out = main.fno_tape(date="2026-11-23", summary=1)
    assert out["minutes"] == 1 and "tape" not in out and out["expected_minutes"] == 376


def test_wired_into_snapshot_and_hook():
    import inspect
    assert "_fno_tape_record(groups" in inspect.getsource(main._fno_by_index_snapshot)
    assert "_fno_tape_window()" in inspect.getsource(main._fno_momo_tick_hook)


def test_journal_workflow():
    y = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/fno-tape-journal.yml"
    s = y.read_text()
    assert "fill=1" in s and "[skip render]" in s and "docs/fno_tape/" in s and "20 10 * * 1-5" in s
