"""B-1675 View 6: most-traded index options grouped per index, route + page + tab. No network."""
import os

import main
from fastapi.testclient import TestClient


def _row(u, k, ot, n, pc=1.0, px=10.0):
    r = {"underlying": u, "strikePrice": k, "optionType": "Call" if ot == "CE" else "Put", "expiryDate": "27-Nov-2026",
         "lastPrice": px, "pChange": pc, "numberOfContractsTraded": n, "openInterest": 5, "underlyingValue": 25600.0}
    r["contract"] = main._fno_label(r)
    return r


def test_group_by_index_sorts_by_contracts_and_trims():
    rows = [_row("NIFTY", 25500, "CE", 100), _row("NIFTY", 25600, "PE", 900), _row("NIFTY", 25700, "CE", "1,500"),
            _row("BANKNIFTY", 52000, "PE", 50), _row("RELIANCE", 1300, "CE", 99999), _row("NIFTY", 25500, "CE", 100)]
    g = main._fno_group_by_index(rows, per_index=2)
    assert set(g) == set(main._FNO_INDEX_UNDERLYINGS)
    assert [r["contract"] for r in g["NIFTY"]] == ["NIFTY 25700 CE 27-Nov-2026", "NIFTY 25600 PE 27-Nov-2026"]
    assert [r["contract"] for r in g["BANKNIFTY"]] == ["BANKNIFTY 52000 PE 27-Nov-2026"]
    assert g["FINNIFTY"] == [] and "RELIANCE" not in g
    assert set(g["NIFTY"][0]) == set(main._FNO_VIEW6_FIELDS)


def test_by_index_route_uses_one_fetch_and_caches(monkeypatch):
    calls = []

    def fake_fetch(lists, limit):
        calls.append((tuple(lists), limit))
        return {"lists": {"index_calls": [_row("NIFTY", 25500, "CE", 10)],
                          "index_puts": [_row("FINNIFTY", 24000, "PE", 20)]}, "errors": {}}
    monkeypatch.setattr(main, "_fno_most_active_fetch", fake_fetch)
    monkeypatch.setattr(main, "_fno_index_day_changes", lambda: {"NIFTY": 0.4, "FINNIFTY": -0.2})
    monkeypatch.setitem(main._FNO_BY_INDEX_CACHE, "data", None)
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: ("op", {}))  # B-1678 chain fallback: no network
    monkeypatch.setattr(main, "_fno_chain_fetch", lambda *a, **k: [])
    monkeypatch.setattr(main, "_FNO_CHAIN_CACHE", {})
    c = TestClient(main.app)
    j = c.get("/fno-most-active-by-index?per_index=5").json()
    assert calls == [(("index_calls", "index_puts"), 50)]
    assert j["ok"] and j["indices"]["NIFTY"]["rows"][0]["contract"] == "NIFTY 25500 CE 27-Nov-2026"
    assert j["indices"]["FINNIFTY"]["day_change_pct"] == -0.2 and j["indices"]["MIDCPNIFTY"]["rows"] == []
    assert "IST" in j["fetched_ist"]
    j2 = c.get("/fno-most-active-by-index?per_index=1").json()
    assert j2["cached"] and len(calls) == 1


def test_index_day_change_parse(monkeypatch):
    class R:
        def __init__(self, b):
            self.b = b

        def read(self, n=-1):
            return self.b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    import json
    import urllib.request

    body = json.dumps({"data": [{"index": "NIFTY 50", "percentChange": 0.51}, {"index": "NIFTY BANK", "percentChange": "-0.3"},
                                {"index": "NIFTY IT", "percentChange": 2}]}).encode()

    class Op:
        def open(self, req, timeout=0):
            return R(body if "allIndices" in req.full_url else b"<html>")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Op())
    assert main._fno_index_day_changes_fetch() == {"NIFTY": 0.51, "BANKNIFTY": -0.3}


def test_page_route_and_tab():
    c = TestClient(main.app)
    r = c.get("/trade-view6")
    assert r.status_code == 200 and "/fno-most-active-by-index" in r.text and "/fno-momo-paper" in r.text
    assert "60000" in r.text and "Contracts traded (lakh)" in r.text
    tabs = open(os.path.join(os.path.dirname(__file__), "..", "static", "trade-view-tabs.html")).read()
    assert 'data-src="/trade-view6"' in tabs and 'data-v="v6"' in tabs
