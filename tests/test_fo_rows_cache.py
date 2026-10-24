"""B-1362: search_scrip re-parses the full scrip master each call, so _fo_rows caches its exact-match rows."""
import nse_fo_chain as nf


def _patch(monkeypatch, resp):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return resp
    monkeypatch.setattr(nf.kotak_neo, "search_scrip", fake)
    return calls


def test_rows_cached_per_underlying_and_type(monkeypatch):
    calls = _patch(monkeypatch, [{"pSymbolName": "NIFTY", "pTrdSymbol": "X"}])
    assert nf._fo_rows("NIFTY", "CE")[0] == nf._fo_rows("NIFTY", "CE")[0]
    assert len(calls) == 1
    nf._fo_rows("NIFTY", "PE")
    assert len(calls) == 2


def test_cache_expires_after_ttl(monkeypatch):
    calls = _patch(monkeypatch, [{"pSymbolName": "NIFTY"}])
    nf._fo_rows("NIFTY", "FUT")
    key = ("NIFTY", "FUT")
    d, ts, rows = nf._fo_rows_cache[key]
    nf._fo_rows_cache[key] = (d, ts - nf._FO_ROWS_CACHE_TTL_SECONDS - 1, rows)
    nf._fo_rows("NIFTY", "FUT")
    assert len(calls) == 2


def test_errors_are_not_cached(monkeypatch):
    calls = _patch(monkeypatch, {"error": ["bad totp"]})
    assert nf._fo_rows("NIFTY", "CE")[1].startswith("search_scrip_error_response")
    nf._fo_rows("NIFTY", "CE")
    assert len(calls) == 2 and not nf._fo_rows_cache
