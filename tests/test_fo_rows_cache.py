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


def test_cache_holds_all_ist_day_and_drops_on_date_change(monkeypatch):
    """B-1447: a same-date entry hours old is still a hit; a new IST date always refetches."""
    import datetime as dt
    calls = _patch(monkeypatch, [{"pSymbolName": "NIFTY"}])
    nf._fo_rows("NIFTY", "FUT")
    key = ("NIFTY", "FUT")
    d, ts, rows = nf._fo_rows_cache[key]
    nf._fo_rows_cache[key] = (d, ts - 6 * 3600, rows)
    nf._fo_rows("NIFTY", "FUT")
    assert len(calls) == 1
    nf._fo_rows_cache[key] = (d - dt.timedelta(days=1), ts, rows)
    nf._fo_rows("NIFTY", "FUT")
    assert len(calls) == 2
