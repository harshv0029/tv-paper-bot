"""B-1578: intraday buy-engine (real_positions) legs are MIS; swing/delivery stays CNC.

BDL 2026-11-12: the intraday buy went in CNC, so the same-day target SELL was rejected
'No Holdings Present'. Every long-side order function now takes the product of the
position it belongs to (default CNC, unchanged for swing), real_positions rows record it,
and reconcile corrects it from Kotak."""
import sqlite3
from contextlib import closing

import pytest

import kotak_real_orders as kro
import main


class _Boom(Exception):
    pass


class _CaptureClient:
    def __init__(self):
        self.calls = []

    def place_order(self, **kw):
        self.calls.append(kw)
        raise _Boom("captured")  # every function catches it and returns ok False: only the kwargs matter here


@pytest.fixture
def client(monkeypatch):
    c = _CaptureClient()
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: c)
    return c


@pytest.mark.parametrize("given,expected", [("MIS", "MIS"), ("mis", "MIS"), ("CNC", "CNC"), (None, "CNC"),
                                            ("", "CNC"), ("NRML", "CNC"), ("junk", "CNC")])
def test_long_product_normalizes(given, expected):
    assert kro._long_product(given) == expected


@pytest.mark.parametrize("call", [
    lambda **k: kro.place_real_entry("BDL-EQ", 1, 1044.9, **k),
    lambda **k: kro.place_real_exit("BDL-EQ", 1, **k),
    lambda **k: kro._place_real_stop_loss_once("BDL-EQ", 1, 1000.0, **k),
    lambda **k: kro.place_real_target("BDL-EQ", 1, 1100.0, **k),
])
def test_long_order_functions_send_the_rows_product(client, call):
    call(product="MIS")
    call()
    assert [c["product"] for c in client.calls] == ["MIS", "CNC"]  # default unchanged for swing/delivery


def test_stop_loss_wrapper_threads_product(monkeypatch):
    seen = []
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro, "apply_entry_day_floor", lambda t, p, side: (p, {}))
    monkeypatch.setattr(kro, "_preclamp_long_stop", lambda t, p: (p, None))
    monkeypatch.setattr(kro, "clamp_stop_to_market", lambda t, p, side: (p, {}))
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda t, q, p, product="CNC": seen.append(product) or {"ok": True, "order_id": "1",
                                                                                "trigger_price": p})
    kro.place_real_stop_loss("BDL-EQ", 1, 1000.0, product="MIS")
    kro.place_real_stop_loss("BDL-EQ", 1, 1000.0)
    assert seen == ["MIS", "CNC"]


def test_retry_wrapper_threads_product(monkeypatch):
    seen = []
    monkeypatch.setattr(kro, "place_real_stop_loss",
                        lambda t, q, p, product="CNC": seen.append(product) or {"ok": True, "order_id": "1"})
    main._place_real_stop_loss_with_retry("BDL-EQ", 1, 1000.0, product="MIS")
    assert seen == ["MIS"]


def test_rp_product_legacy_rows_stay_cnc():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE t (symbol TEXT)")  # a pre-B-1578 row shape, no product column
    conn.execute("INSERT INTO t VALUES ('BDL.NS')")
    legacy = conn.execute("SELECT * FROM t").fetchone()
    assert main._rp_product(legacy) == "CNC"
    assert main._rp_product(None) == "CNC"
    assert main._rp_product({"product": None}) == "CNC"
    assert main._rp_product({"product": "MIS"}) == "MIS"
    assert main._rp_product({"product": "NRML"}) == "CNC"
    assert main.INTRADAY_REAL_PRODUCT == "MIS"


def test_kotak_row_product():
    assert main._kotak_row_product({"prod": "MIS"}) == "MIS"
    assert main._kotak_row_product({"prod": "cnc"}) == "CNC"
    assert main._kotak_row_product({"prod": "NRML"}) is None
    assert main._kotak_row_product({}) is None
    assert main._kotak_row_product(None) is None


def test_real_positions_has_product_column_and_upstash_restore_keeps_it(monkeypatch):
    with closing(main.get_db()) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(real_positions)").fetchall()}
        assert "product" in cols
        conn.execute("DELETE FROM real_positions WHERE symbol = 'B1578TEST.NS'")
        conn.commit()
    import json
    payload = json.dumps({"rows": [{"symbol": "B1578TEST.NS", "kotak_trading_symbol": "B1578TEST-EQ", "qty": 1,
                                    "entry_price": 100.0, "opened_at": 1.0, "day": "2026-11-16",
                                    "product": "MIS"}]})
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")

    class _R:
        status_code = 200

        def json(self):
            return {"result": payload}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: _R())
    monkeypatch.setattr(main, "_upstash_unmask", lambda key, v: v)
    assert main.hydrate_real_positions_from_external() is True
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT product FROM real_positions WHERE symbol = 'B1578TEST.NS'").fetchone()
        conn.execute("DELETE FROM real_positions WHERE symbol = 'B1578TEST.NS'")
        conn.commit()
    assert row is not None and row["product"] == "MIS"
