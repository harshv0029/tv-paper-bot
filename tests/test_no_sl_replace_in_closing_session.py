import types
import kotak_real_orders as kro


def _setup(monkeypatch, closing):
    rows = [{"trdSym": "RVNL-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending",
             "nOrdNo": "1", "trgPrc": "300", "qty": "2"}]
    client = types.SimpleNamespace(order_report=lambda: {"data": rows})
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: client)
    monkeypatch.setattr(kro, "_in_closing_session", lambda: closing)
    calls = []
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: calls.append(("cancel", oid)) or {"ok": True})
    monkeypatch.setattr(kro, "place_real_stop_loss",
                        lambda *a: calls.append(("place", a)) or {"ok": True, "order_id": "2", "trigger_price": a[2]})
    return calls


def test_no_cancel_after_1515(monkeypatch):
    calls = _setup(monkeypatch, True)
    res = kro.ensure_resting_sl("RVNL-EQ", 2, 310.0)
    assert res["action"] == "skipped_closing_session" and calls == []


def test_ratchet_still_works_before_1515(monkeypatch):
    calls = _setup(monkeypatch, False)
    res = kro.ensure_resting_sl("RVNL-EQ", 2, 310.0)
    assert res["action"] == "replaced" and calls[0] == ("cancel", "1")
