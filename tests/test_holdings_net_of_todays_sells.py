import sys, types
import main


def _fake(monkeypatch, holdings, positions):
    k = types.SimpleNamespace(holdings=lambda: {"data": holdings}, positions=lambda: {"data": positions})
    monkeypatch.setitem(sys.modules, "kotak_neo", k)


H = [{"exchangeSegment": "nse_cm", "symbol": "DRREDDY", "series": "EQ", "quantity": 1, "averagePrice": 1209.49},
     {"exchangeSegment": "nse_cm", "symbol": "NYKAA", "series": "EQ", "quantity": 1, "averagePrice": 340.11}]


def test_sold_today_holding_is_dropped(monkeypatch):
    _fake(monkeypatch, H, [{"exSeg": "nse_cm", "trdSym": "DRREDDY-EQ", "flBuyQty": "0", "flSellQty": "1"}])
    out = main._kotak_holdings_open_by_trdsym()
    assert "DRREDDY-EQ" not in out and out["NYKAA-EQ"]["qty"] == 1


def test_positions_failure_keeps_holding(monkeypatch):
    k = types.SimpleNamespace(holdings=lambda: {"data": H}, positions=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setitem(sys.modules, "kotak_neo", k)
    assert "DRREDDY-EQ" in main._kotak_holdings_open_by_trdsym()
