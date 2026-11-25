"""B-1712: View 6 option chains (BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 404, SENSEX 403 live 25-Nov-2026)."""
import io
import json
import urllib.error

import pytest

import main
import nse_fo_chain
from tests.test_fno_momo_paper_b1676 import V3

REAL_KOTAK_CHAIN = main._fno_kotak_chain


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
    assert main._FNO_CHAIN_CACHE[("MIDCPNIFTY", "")]["error"].endswith("contract-info: HTTP 403")


def test_404_named_by_step(monkeypatch):
    def fake(op, hdrs, path, *a, **k):
        if "contract-info" in path:
            return {"expiryDates": ["30-Dec-2099"]}
        raise _http(404)
    monkeypatch.setattr(main, "_nse_get_json", fake)
    main._fno_chain_fetch("NIFTYNXT50")
    assert main._FNO_CHAIN_CACHE[("NIFTYNXT50", "")]["error"].endswith("v3 30-Dec-2099: HTTP 404")


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


def _scrip(u, exp, strike, ot, tok, lot=30):
    return {"pSymbolName": u, "pOptionType": ot, "pExpiryDate": exp, "dStrikePrice;": strike * 100, "pSymbol": tok,
            "lLotSize": lot}


def _kotak_setup(monkeypatch, quotes):
    monkeypatch.setattr(main, "_fno_kotak_chain", REAL_KOTAK_CHAIN)
    monkeypatch.setattr(main, "_FNO_KOTAK_CONTRACTS", {})
    monkeypatch.setattr(main, "_FNO_KOTAK_SPOT_CACHE", {})
    monkeypatch.setattr(main, "ist_now", lambda: main.dt.datetime(2026, 11, 25, 10, 0))
    rows = {"ce": [_scrip("BANKNIFTY", "30Dec2026", k, "ce", 1000 + k // 100) for k in range(50000, 62000, 100)]
                  + [_scrip("BANKNIFTY", "23Nov2026", 59000, "ce", 9)],
            "pe": [_scrip("BANKNIFTY", "30Dec2026", 59000, "pe", 77)]}
    monkeypatch.setattr(nse_fo_chain, "_fo_rows_uncached", lambda u, option_type=None: (rows[option_type], None))
    monkeypatch.setattr(main, "_FNO_INDEX_DETAIL_CACHE", {"data": {"BANKNIFTY": {"last": 59040.0}}})
    asked = []

    def fake_quotes(tokens, quote_type="ltp"):
        asked.append([t["instrument_token"] for t in tokens])
        return [dict(quotes.get(t["instrument_token"], {"ltp": "0", "last_volume": "0"}),
                     exchange_token=t["instrument_token"]) for t in tokens]
    import kotak_neo
    monkeypatch.setattr(kotak_neo, "quotes", fake_quotes)
    return asked


def test_kotak_chain_band_around_spot_nearest_upcoming_expiry(monkeypatch):
    asked = _kotak_setup(monkeypatch, {"1590": {"ltp": "250.5", "per_change": "12.5", "last_volume": "3000",
                                                "open_int": "60000"},
                                       "77": {"ltp": "180", "ohlc": {"close": "200"}, "last_volume": "600"}})
    rows, err = main._fno_kotak_chain("BANKNIFTY")
    assert err is None
    toks = asked[0]
    assert "9" not in toks and len(toks) == 22  # lapsed 23-Nov skipped; 21 CE strikes around 59000 + 1 PE
    assert {"1580", "1600"} <= set(toks) and "1500" not in toks
    ce = next(r for r in rows if r["optionType"] == "CE")
    assert ce["contract"] == "BANKNIFTY 59000 CE 30-Dec-2026" and ce["numberOfContractsTraded"] == 100
    assert ce["pChange"] == 12.5 and ce["openInterest"] == 2000 and ce["source"] == "kotak"
    pe = next(r for r in rows if r["optionType"] == "PE")
    assert pe["pChange"] == -10.0  # from ohlc.close when per_change is absent


def test_kotak_first_then_cached_60s(monkeypatch):
    asked = _kotak_setup(monkeypatch, {"1590": {"ltp": "250", "per_change": "1", "last_volume": "300"}})
    monkeypatch.setattr(main, "_nse_get_json", lambda *a, **k: pytest.fail("NSE called although Kotak answered"))
    assert main._fno_chain_fetch("BANKNIFTY")[0]["source"] == "kotak"
    assert main._fno_chain_fetch("BANKNIFTY", ttl=1)[0]["source"] == "kotak" and len(asked) == 1


def test_kotak_sensex_spot_and_untraded_reported(monkeypatch):
    _kotak_setup(monkeypatch, {})
    monkeypatch.setattr(main, "_FNO_INDEX_DETAIL_CACHE", {"data": {}})
    import kotak_neo
    monkeypatch.setattr(kotak_neo, "quotes", lambda tokens, quote_type="ltp": [
        {"exchange_token": t["instrument_token"], "ltp": "83863.02", "per_change": "0.9"} if t["instrument_token"]
        == "SENSEX" else {"exchange_token": t["instrument_token"], "ltp": "0"} for t in tokens])
    assert main._fno_kotak_spot("SENSEX") == (83863.02, 0.9)
    rows, err = main._fno_kotak_chain("BANKNIFTY")
    assert rows == [] and "none traded today" in err
