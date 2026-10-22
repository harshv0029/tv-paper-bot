"""B-1337 (YESBANK 22 Oct): holdings() lists shares sold today until T+1. With positions() failing, the heal sent
3 SELL SLs on 20 shares already sold at 09:17. Today's complete delivery sells in the order book must net them out."""
import types

import main

YES_HOLD = {"exchangeSegment": "nse_cm", "symbol": "YESBANK", "series": "EQ", "quantity": 20, "averagePrice": 16.38}
YES_SOLD = {"trdSym": "YESBANK-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "complete", "qty": "20", "fldQty": "20",
            "prod": "CNC"}


def _fake(monkeypatch, positions_raises=True, orders=(YES_SOLD,)):
    def positions():
        if positions_raises:
            raise TimeoutError("Request timeout after 30 seconds")
        return {"data": []}
    fake = types.SimpleNamespace(holdings=lambda: {"data": [YES_HOLD]}, positions=positions,
                                 order_report=lambda *a, **k: {"data": list(orders)})
    monkeypatch.setitem(__import__("sys").modules, "kotak_neo", fake)


def test_order_book_sell_nets_holding_when_positions_fails(monkeypatch):
    _fake(monkeypatch)
    assert "YESBANK-EQ" not in main._kotak_holdings_open_by_trdsym()


def test_intraday_or_rejected_sells_do_not_net(monkeypatch):
    mis = dict(YES_SOLD, prod="MIS")
    rej = dict(YES_SOLD, ordSt="rejected")
    _fake(monkeypatch, orders=(mis, rej))
    assert main._kotak_holdings_open_by_trdsym()["YESBANK-EQ"]["qty"] == 20


def test_partial_sell_leaves_remainder(monkeypatch):
    _fake(monkeypatch, orders=(dict(YES_SOLD, qty="5", fldQty="5"),))
    assert main._kotak_holdings_open_by_trdsym()["YESBANK-EQ"]["qty"] == 15


def test_heal_refuses_sold_today_holding():
    res = main._heal_swing_holding_core("YESBANK-EQ", {"qty": 20, "avg_price": 16.38, "symbol": "YESBANK"}, [YES_SOLD])
    assert res.get("status", "").startswith("sold_today")
