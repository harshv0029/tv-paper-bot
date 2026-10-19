"""B-967: the 1-share overnight short test endpoint is token-gated, qty-fixed, and
never leaves a short open without a stop-loss."""
import pytest
from fastapi.testclient import TestClient

import main
import kotak_real_orders as kro


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "KOTAK_NEO_API_TOKEN", "tok")
    monkeypatch.setattr(main, "_b967_log", lambda *a, **k: None)
    return TestClient(main.app)


def _post(client, **p):
    p.setdefault("token", "tok")
    return client.post("/kotak-neo/b967-short-test", params=p)


def test_requires_token(client):
    assert _post(client, token="bad", action="enter", kotak_trading_symbol="X-EQ", ltp=50).status_code == 401


def test_rejects_expensive_or_bad_symbol(client, monkeypatch):
    called = []
    monkeypatch.setattr(kro, "place_real_short_entry", lambda *a, **k: called.append(1))
    assert "error" in _post(client, action="enter", kotak_trading_symbol="X-EQ", ltp=500).json()
    assert "error" in _post(client, action="enter", kotak_trading_symbol="X-BE", ltp=50).json()
    assert not called


def test_enter_places_qty1_with_sl(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(kro, "place_real_short_entry",
                        lambda t, q, l, product="MIS": seen.update(q=q, prod=product) or {"ok": True, "order_id": "1", "fill_price": 100.0})
    monkeypatch.setattr(kro, "place_real_short_stop_loss",
                        lambda t, q, trig, product="MIS": seen.update(trig=trig) or {"ok": True, "order_id": "2"})
    r = _post(client, action="enter", kotak_trading_symbol="X-EQ", ltp=100).json()
    assert seen == {"q": 1, "prod": "NRML", "trig": 105.0} and r["unwound"] is None


def test_unwinds_when_sl_fails(client, monkeypatch):
    monkeypatch.setattr(kro, "place_real_short_entry", lambda *a, **k: {"ok": True, "order_id": "1", "fill_price": 100.0})
    monkeypatch.setattr(kro, "place_real_short_stop_loss", lambda *a, **k: {"ok": False, "detail": "rej"})
    covered = []
    monkeypatch.setattr(kro, "place_real_short_cover", lambda t, q, product="MIS": covered.append(q) or {"ok": True})
    r = _post(client, action="enter", kotak_trading_symbol="X-EQ", ltp=100).json()
    assert covered == [1] and r["unwound"]["ok"]


def test_cover_cancels_sl_then_covers(client, monkeypatch):
    order = []
    monkeypatch.setattr(kro, "cancel_existing_resting_sl_short", lambda t: order.append("cancel") or {})
    monkeypatch.setattr(kro, "place_real_short_cover", lambda t, q, product="MIS": order.append("cover") or {"ok": True})
    _post(client, action="cover", kotak_trading_symbol="X-EQ")
    assert order == ["cancel", "cover"]
