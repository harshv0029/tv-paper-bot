import main


def test_gross_holdings_only_nse_cm(monkeypatch):
    import sys, types
    k = types.SimpleNamespace(holdings=lambda: {"data": [
        {"exchangeSegment": "nse_cm", "symbol": "NYKAA", "series": "EQ", "quantity": 1}]})
    monkeypatch.setitem(sys.modules, "kotak_neo", k)
    assert main._kotak_holdings_gross_qty() == {"NYKAA-EQ": 1.0}


def test_holdings_failure_gives_empty(monkeypatch):
    import sys, types
    k = types.SimpleNamespace(holdings=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setitem(sys.modules, "kotak_neo", k)
    assert main._kotak_holdings_gross_qty() == {}
