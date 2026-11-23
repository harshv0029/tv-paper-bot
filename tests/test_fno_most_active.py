"""B-1671: /fno-most-active parsing, labels, cache, list validation."""
import main


def test_label_option_and_future():
    assert main._fno_label({"underlying": "NIFTY", "strikePrice": 25500, "optionType": "Call",
                            "expiryDate": "27-Nov-2026"}) == "NIFTY 25500 CE 27-Nov-2026"
    assert main._fno_label({"underlying": "BANKNIFTY", "strikePrice": "52000.00", "optionType": "Put",
                            "expiryDate": "25-Nov-2026"}) == "BANKNIFTY 52000 PE 25-Nov-2026"
    assert main._fno_label({"underlying": "RELIANCE", "instrumentType": "FUTSTK",
                            "expiryDate": "25-Nov-2026"}) == "RELIANCE FUT 25-Nov-2026"


def test_rows_from_nested_payload_trims_and_limits():
    payload = {"volume": {"data": [
        {"underlying": "NIFTY", "strikePrice": 25500, "optionType": "Call", "expiryDate": "27-Nov-2026",
         "numberOfContractsTraded": 123, "openInterest": 9, "junk": "x"}] * 5}}
    rows = main._fno_rows_from_payload(payload, 3)
    assert len(rows) == 3
    assert rows[0]["contract"] == "NIFTY 25500 CE 27-Nov-2026"
    assert rows[0]["numberOfContractsTraded"] == 123 and "junk" not in rows[0]
    assert main._fno_rows_from_payload({"x": 1}, 5) == []


def test_route_invalid_list_and_cache(monkeypatch):
    assert "valid_lists" in main.fno_most_active(lists="bogus")
    calls = []

    def fake(names, limit):
        calls.append(names)
        return {"lists": {n: [{"contract": "NIFTY 25500 CE"}] for n in names}, "errors": {}}
    main._FNO_MOST_ACTIVE_CACHE.update(ts=0.0, key=None, data=None)
    monkeypatch.setattr(main, "_fno_most_active_fetch", fake)
    a = main.fno_most_active(lists="index_calls", limit=5)
    b = main.fno_most_active(lists="index_calls", limit=5)
    assert a["ok"] and a["cached"] is False and b["cached"] is True and len(calls) == 1
    assert a["fetched_ist"].endswith("IST")


def test_route_not_cached_on_failure(monkeypatch):
    main._FNO_MOST_ACTIVE_CACHE.update(ts=0.0, key=None, data=None)
    monkeypatch.setattr(main, "_fno_most_active_fetch",
                        lambda n, l: {"lists": {}, "errors": {"handshake": "403"}})
    r = main.fno_most_active(lists="contracts")
    assert r["ok"] is False and main._FNO_MOST_ACTIVE_CACHE["data"] is None
