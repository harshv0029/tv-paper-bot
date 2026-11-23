"""B-1688: the tape stores ATM +-10 strikes (CE+PE, nearest expiry) of every index chain plus India VIX; an index
whose chain fails falls back to its most-active rows; Upstash values are zlib+b64 and restore on wipe. No network."""
import datetime as dt
import os
import sqlite3
import tempfile

import pytest

import main
from tests.test_fno_tape_b1687 import FakeUpstash, GROUPS, MON


def _leg(u, k, ot, spot, exp="27-Nov-2026"):
    r = {"underlying": u, "strikePrice": k, "optionType": ot, "expiryDate": exp, "lastPrice": 10.0, "pChange": 1.0,
         "numberOfContractsTraded": 100, "openInterest": 500, "changeinOpenInterest": 5, "impliedVolatility": 13.0,
         "underlyingValue": spot}
    r["contract"] = main._fno_label(r)
    return r


def _chain(u="NIFTY", spot=25512.0, step=50, base=24000, n=60):
    rows = []
    for i in range(n):
        for ot in ("CE", "PE"):
            rows.append(_leg(u, base + step * i, ot, spot))
    rows.append(_leg(u, 25500, "CE", spot, exp="04-Dec-2026"))  # a later expiry is ignored
    return rows


@pytest.fixture(autouse=True)
def env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    monkeypatch.setattr(main, "_FNO_TAPE_STATE", {"last_minute": None, "rows_today": 0, "day": None, "upstash_ok": 0,
                                                  "upstash_fail": 0, "skipped_budget": 0, "last_error": None,
                                                  "atm_indices": []})
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


def test_atm_window_is_21_strikes_ce_pe_nearest_expiry():
    rows, atm = main._fno_atm_window(_chain())
    assert atm == 25500
    ks = sorted({r["strikePrice"] for r in rows})
    assert len(ks) == 21 and ks[0] == 25000 and ks[-1] == 26000
    assert len(rows) == 42 and {r["optionType"] for r in rows} == {"CE", "PE"}
    assert {r["expiryDate"] for r in rows} == {"27-Nov-2026"}


def test_atm_window_edges_and_bad_input():
    rows, atm = main._fno_atm_window(_chain(spot=24010.0))  # ATM at the lowest strike: only 11 strikes exist
    assert atm == 24000 and len({r["strikePrice"] for r in rows}) == 11
    assert main._fno_atm_window([]) == ([], None)
    assert main._fno_atm_window([{"contract": "x", "strikePrice": 100}]) == ([], None)  # no spot


def test_chains_use_60s_ttl_and_one_opener(monkeypatch):
    calls, openers = [], []
    monkeypatch.setattr(main, "_nse_opener", lambda: openers.append(1) or ("op", {}))
    monkeypatch.setattr(main, "_FNO_CHAIN_CACHE", {})

    def fetch(u, exp, opener, ttl=None):
        calls.append((u, ttl))
        if u == "FINNIFTY":
            raise RuntimeError("chain down")
        return _chain(u) if u != "SENSEX" else []
    monkeypatch.setattr(main, "_fno_chain_fetch", fetch)
    out = main._fno_tape_chains()
    assert len(openers) == 1 and all(t == main.FNO_TAPE_CHAIN_S for _, t in calls)
    assert len(calls) == len(main._FNO_INDEX_UNDERLYINGS)
    assert "FINNIFTY" not in out and "SENSEX" not in out and out["NIFTY"][1] == 25500
    assert "FINNIFTY" in main._FNO_TAPE_STATE["last_error"]


def test_payload_atm_chain_fallback_most_active_and_vix():
    chains = {"NIFTY": main._fno_atm_window(_chain())}
    p = main._fno_tape_payload(GROUPS, {"NIFTY": 0.4, "INDIAVIX": 3.2}, chains,
                               {"INDIAVIX": {"last": 14.1, "open": 13.7}})
    assert p["src"] == {"NIFTY": "atm_chain", "BANKNIFTY": "most_active"}
    assert len(p["rows"]["NIFTY"]) == 42 and p["atm"] == {"NIFTY": 25500}
    assert p["vix"] == {"last": 14.1, "pct": 3.2}
    assert main._fno_tape_payload({}, {}, {}, None)["vix"] == {"last": None, "pct": None}


def test_record_stores_chain_compresses_upstash_and_restores(env):
    chains = {u: main._fno_atm_window(_chain(u)) for u in ("NIFTY", "BANKNIFTY")}
    assert main._fno_tape_record(GROUPS, {"INDIAVIX": -1.5}, now=MON, chains=chains,
                                 index_detail={"INDIAVIX": {"last": 15.0}})
    (key, val), = env.kv.items()
    assert key == "fno_tape_v2:2026-11-23:1000" and val.startswith("z:")
    assert main._FNO_TAPE_STATE["atm_indices"] == ["BANKNIFTY", "NIFTY"]
    os.remove(main.DB_PATH)  # Render wipe
    sqlite3.connect(main.DB_PATH).close()
    t = main._fno_tape_export("2026-11-23", fill=True)["tape"][0]
    assert t["vix"] == {"last": 15.0, "pct": -1.5} and len(t["rows"]["NIFTY"]) == 42


def test_record_fetches_chains_once_per_minute(monkeypatch):
    n = []
    monkeypatch.setattr(main, "_fno_tape_chains", lambda: n.append(1) or {})
    main._fno_tape_record(GROUPS, {}, now=MON)
    main._fno_tape_record(GROUPS, {}, now=MON.replace(second=30))
    assert n == [1]


def test_unpack_reads_plain_json_too():
    assert main._fno_tape_unpack('{"a":1}') == {"a": 1}
    assert main._fno_tape_unpack(main._fno_tape_pack('{"a":1}')) == {"a": 1}


def test_view6_route_carries_vix(monkeypatch):
    monkeypatch.setattr(main, "_fno_view_snapshot", lambda: {"groups": {}, "index_pct": {"INDIAVIX": 2.5},
                                                             "index_detail": {"INDIAVIX": {"last": 14.9}}, "ok": True})
    assert main.fno_most_active_by_index()["india_vix"] == {"last": 14.9, "pct": 2.5}


def test_b1690_greeks_per_leg():
    now = dt.datetime(2026, 11, 23, 10, 0)
    w, atm = main._fno_atm_window(_chain())
    T = main._fno_years_to_expiry("27-Nov-2026", now)
    for r in w:
        r["lastPrice"] = round(main._bs_price(r["underlyingValue"], r["strikePrice"], T, 0.13, r["optionType"]), 2)
    p = main._fno_tape_payload({}, {}, {"NIFTY": (w, atm)}, None, now)
    assert p["cols"][-6:] == list(main.FNO_TAPE_GREEK_COLS)
    rows = {r[0]: dict(zip(p["cols"], r)) for r in p["rows"]["NIFTY"]}
    ce, pe = rows["NIFTY 25500 CE 27-Nov-2026"], rows["NIFTY 25500 PE 27-Nov-2026"]
    assert 0 < ce["delta"] < 1 and -1 < pe["delta"] < 0 and ce["gamma"] > 0
    assert ce["theta_per_day"] < 0 and ce["vega_per_vol_pt"] > 0 and 3 < ce["days_to_expiry"] < 5
    bad = main._fno_tape_greeks({"contract": "x", "lastPrice": 0}, now)
    assert len(bad) == 6
