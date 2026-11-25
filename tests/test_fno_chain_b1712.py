"""B-1712: View 6 option chains (BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 404, SENSEX 403 live 25-Nov-2026)."""
import io
import json
import urllib.error

import pytest

import main
from tests.test_fno_momo_paper_b1676 import V3


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(main, "_FNO_CHAIN_CACHE", {})
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: ("op", {}))


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def test_retired_legacy_endpoint_never_called_and_v3_shape_reported(monkeypatch):
    paths = []

    def fake(op, hdrs, path, *a, **k):
        paths.append(path)
        if "contract-info" in path:
            return {"expiryDates": ["30-Dec-2099"]}
        return {"records": {"data": [{"strikePrice": 1, "CE": {"foo": 1}}]}}
    monkeypatch.setattr(main, "_nse_get_json", fake)
    assert main._fno_chain_fetch("BANKNIFTY") == []
    assert not any("option-chain-indices" in p for p in paths)
    err = main._FNO_CHAIN_CACHE[("BANKNIFTY", "")]["error"]
    assert "v3 30-Dec-2099: 0 rows" in err and "leg foo" in err


def test_lapsed_first_expiry_skipped(monkeypatch):
    paths = []

    def fake(op, hdrs, path, *a, **k):
        paths.append(path)
        return {"expiryDates": ["23-Nov-2026", "30-Dec-2026"]} if "contract-info" in path else V3
    monkeypatch.setattr(main, "_nse_get_json", fake)
    monkeypatch.setattr(main, "ist_now", lambda: main.dt.datetime(2026, 11, 25, 9, 30))
    rows = main._fno_chain_fetch("FINNIFTY")
    assert len(rows) == 2 and "expiry=30-Dec-2026" in paths[1] and len(paths) == 2


def test_second_expiry_tried_when_first_has_no_rows(monkeypatch):
    def fake(op, hdrs, path, *a, **k):
        if "contract-info" in path:
            return {"expiryDates": ["29-Dec-2099", "30-Dec-2026"]}
        return V3 if "30-Dec-2026" in path else {"records": {"data": []}}
    monkeypatch.setattr(main, "_nse_get_json", fake)
    monkeypatch.setattr(main, "ist_now", lambda: main.dt.datetime(2026, 11, 25, 9, 30))
    assert len(main._fno_chain_fetch("FINNIFTY")) == 2


def test_403_retried_once_with_fresh_session_then_named(monkeypatch):
    openers, calls = [], []
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: openers.append(1) or ("op", {}))

    def fake(op, hdrs, path, *a, **k):
        calls.append(path)
        raise _http(403)
    monkeypatch.setattr(main, "_nse_get_json", fake)
    assert main._fno_chain_fetch("MIDCPNIFTY") == []
    assert len(calls) == 2 and len(openers) == 2  # first handshake + one fresh retry
    assert main._FNO_CHAIN_CACHE[("MIDCPNIFTY", "")]["error"] == "contract-info: HTTP 403"


def test_404_named_by_step(monkeypatch):
    def fake(op, hdrs, path, *a, **k):
        if "contract-info" in path:
            return {"expiryDates": ["30-Dec-2099"]}
        raise _http(404)
    monkeypatch.setattr(main, "_nse_get_json", fake)
    main._fno_chain_fetch("NIFTYNXT50")
    assert main._FNO_CHAIN_CACHE[("NIFTYNXT50", "")]["error"] == "v3 30-Dec-2099: HTTP 404"


def test_expiry_match_ignores_case():
    v3 = json.loads(json.dumps(V3).replace("30-Dec-2026", "30-DEC-2026"))
    rows = main._fno_chain_rows(v3, "FINNIFTY", "30-Dec-2026")
    assert [r["contract"] for r in rows] == ["FINNIFTY 23000 CE 30-Dec-2026", "FINNIFTY 23000 PE 30-Dec-2026"]


def test_bse_error_names_the_step(monkeypatch):
    class Op:
        def open(self, req, timeout=None):
            if "api.bseindia.com" in req.full_url:
                raise _http(403)
            return io.BytesIO(b"<html>")
    monkeypatch.setattr(main.urllib.request if hasattr(main, "urllib") else __import__("urllib.request").request,
                        "build_opener", lambda *a, **k: Op())
    rows, err = main._bse_sensex_chain()
    assert rows == [] and err.startswith("BSE ddlExpiry_IV")
