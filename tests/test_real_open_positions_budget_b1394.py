"""B-1394: GET /real-open-positions answers within its time budget. A slow/failed Kotak call returns the last-good
rows (stale=true, IST as_of); a complete fresh build refreshes that copy. Display only."""
import json
import os
import tempfile
import time
from contextlib import closing
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", ("AAA.NS", "AAA-EQ", 2, 100.0, "1", 1.0, "2026-10-29"))
        conn.commit()


def _kotak(slow_s=0.0):
    k = MagicMock()

    def _pos():
        if slow_s:
            time.sleep(slow_s)
        return {"data": [{"exSeg": "nse_cm", "trdSym": "AAA-EQ", "flBuyQty": "2", "flSellQty": "0", "buyAmt": "200"}]}
    k.positions.side_effect = _pos
    k.holdings.return_value = {"data": []}
    return k


def _px(*_a, **_k):
    return pd.DataFrame({"Close": [101.0]})


def test_fresh_success_refreshes_last_good_copy():
    _fresh_db()
    with patch.dict("sys.modules", {"kotak_neo": _kotak()}), patch("main.fetch_ohlc", side_effect=_px):
        out = main.get_real_open_positions()
    assert out["stale"] is False and out["as_of"].endswith(" IST")
    assert out["count"] == 1
    assert main._real_open_positions_last_good["payload"]["count"] == 1
    assert main._real_open_positions_last_good["as_of"].endswith(" IST")


def test_slow_kotak_returns_cached_rows_within_budget(monkeypatch):
    _fresh_db()
    main._real_open_positions_last_good.update(
        payload={"open_real_positions": [{"symbol": "CACHED.NS"}], "count": 1}, as_of="2026-10-28 23:59:00 IST")
    monkeypatch.setattr(main, "REAL_OPEN_POSITIONS_KOTAK_CALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(main, "REAL_OPEN_POSITIONS_BUDGET_S", 3.0)
    t0 = time.time()
    with patch.dict("sys.modules", {"kotak_neo": _kotak(slow_s=2.0)}), patch("main.fetch_ohlc", side_effect=_px):
        out = main.get_real_open_positions()
    assert time.time() - t0 < 3.0
    assert out["stale"] is True
    assert out["as_of"] == "2026-10-28 23:59:00 IST"
    assert out["open_real_positions"] == [{"symbol": "CACHED.NS"}]
    # the incomplete build must not overwrite the last-good copy
    assert main._real_open_positions_last_good["payload"]["open_real_positions"][0]["symbol"] == "CACHED.NS"


def test_build_over_budget_returns_cached_rows(monkeypatch):
    main._real_open_positions_last_good.update(
        payload={"open_real_positions": [], "count": 0}, as_of="2026-10-28 23:00:00 IST")
    monkeypatch.setattr(main, "REAL_OPEN_POSITIONS_BUDGET_S", 0.3)
    monkeypatch.setattr(main, "_real_open_positions_build", lambda: (time.sleep(1.0), ({}, False))[1])
    t0 = time.time()
    out = main.get_real_open_positions()
    assert time.time() - t0 < 1.0
    assert out["stale"] is True and "budget" in out["stale_reason"]


def test_no_cache_and_nothing_finished_is_503(monkeypatch):
    monkeypatch.setattr(main, "REAL_OPEN_POSITIONS_BUDGET_S", 0.2)
    monkeypatch.setattr(main, "_real_open_positions_build", lambda: (time.sleep(0.6), ({}, False))[1])
    with pytest.raises(HTTPException) as ei:
        main.get_real_open_positions()
    assert ei.value.status_code == 503


def test_kotak_failure_without_cache_returns_partial_fresh_rows():
    _fresh_db()
    k = MagicMock()
    k.positions.side_effect = RuntimeError("kotak down")
    with patch.dict("sys.modules", {"kotak_neo": k}), patch("main.fetch_ohlc", side_effect=_px):
        out = main.get_real_open_positions()
    assert out.get("partial") is True and out["stale"] is False
    assert [r["symbol"] for r in out["open_real_positions"]] == ["AAA.NS"]
    assert main._real_open_positions_last_good["payload"] is None


def test_last_good_mirrors_to_upstash_and_restores(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    main._real_open_positions_last_good.update(
        payload={"open_real_positions": [{"symbol": "Z.NS"}], "count": 1}, as_of="2026-10-29 00:10:00 IST")
    assert main._rop_push_last_good(force=True) is True
    assert json.loads(store[main._REAL_OPEN_POSITIONS_REDIS_KEY])["as_of"] == "2026-10-29 00:10:00 IST"
    main._real_open_positions_last_good.update(payload=None, as_of=None)  # simulated restart wipe
    assert main.hydrate_real_open_positions_last_good_from_external() == 1
    assert main._real_open_positions_last_good["payload"]["open_real_positions"] == [{"symbol": "Z.NS"}]
