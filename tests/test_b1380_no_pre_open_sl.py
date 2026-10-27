"""B-1380: no SL order is sent to Kotak before 09:15 IST (pre-open rejects it with 16387)."""
import kotak_real_orders as kro


def test_pre_open_sl_not_sent(monkeypatch):
    monkeypatch.setattr(kro, "_before_equity_open", lambda: True)
    sent = []
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked", lambda *a: sent.append(a) or {"ok": True})
    res = kro.place_real_stop_loss("WIPRO-EQ", 1, 175.12)
    assert sent == [] and res["ok"] is False and res["action"] == "skipped_pre_open"
    assert "WIPRO-EQ" not in kro._RECENT_SL_PLACED


def test_in_session_sl_sent(monkeypatch):
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked",
                        lambda *a: {"ok": True, "order_id": "1", "trigger_price": 175.12})
    assert kro.place_real_stop_loss("WIPRO-EQ", 1, 175.12)["ok"] is True
