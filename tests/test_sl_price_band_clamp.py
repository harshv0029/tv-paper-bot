import kotak_real_orders as k


def test_price_band_rejection_retries_at_band_floor(monkeypatch):
    calls = []

    def once(sym, qty, trig):
        calls.append(trig)
        if trig < 162.6:
            return {"ok": False, "detail": "order 1 rejected: Order price is outside the valid price range."}
        return {"ok": True, "order_id": "9", "trigger_price": trig}

    monkeypatch.setattr(k, "_place_real_stop_loss_once", once)
    monkeypatch.setattr(k, "_reference_prices", lambda s: (180.70, 184.45))
    r = k.place_real_stop_loss("UNIONBANK-EQ", 1, 159.67)
    assert r["ok"] and r["band_clamped_from"] == 159.67
    assert 162.6 < calls[-1] < 184.45 * 0.995


def test_other_rejection_is_not_retried(monkeypatch):
    n = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once",
                        lambda *a: n.append(1) or {"ok": False, "detail": "T1 holdings"})
    monkeypatch.setattr(k, "_reference_prices", lambda s: (180.70, 184.45))
    assert not k.place_real_stop_loss("X-EQ", 1, 150.0)["ok"] and len(n) == 1
