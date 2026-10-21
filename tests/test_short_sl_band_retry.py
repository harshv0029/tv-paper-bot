"""B-1305: a short's buy-stop rejected above the upper price band is retried at a band ceiling."""
import kotak_real_orders as kro


def _setup(monkeypatch, outcomes):
    calls = []

    def once(sym, qty, trig, product="MIS"):
        calls.append(trig)
        return outcomes(trig)
    monkeypatch.setattr(kro, "_place_real_short_stop_loss_once", once)
    monkeypatch.setattr(kro, "_reference_prices", lambda s: (100.0, 104.0))
    monkeypatch.setattr(kro, "_tick_size_for", lambda s: 0.05)
    return calls


def test_retries_at_upper_band_ceiling(monkeypatch):
    calls = _setup(monkeypatch, lambda t: {"ok": t < 112, "order_id": "9", "trigger_price": t,
                                           "detail": "Order price is outside the valid price range"})
    r = kro.place_real_short_stop_loss("X-EQ", 1, 118.0)
    assert r["ok"] and r["band_clamped_from"] == 118.0
    assert calls[0] == 118.0 and 104 * 1.005 < calls[1] < 118.0


def test_other_rejection_not_retried(monkeypatch):
    calls = _setup(monkeypatch, lambda t: {"ok": False, "detail": "insufficient margin"})
    r = kro.place_real_short_stop_loss("X-EQ", 1, 118.0)
    assert not r["ok"] and calls == [118.0]


def test_never_lowered_to_the_market(monkeypatch):
    monkeypatch.setattr(kro, "_reference_prices", lambda s: (100.0, 109.8))
    calls = []
    monkeypatch.setattr(kro, "_place_real_short_stop_loss_once",
                        lambda s, q, t, p="MIS": calls.append(t) or {"ok": False, "detail": "circuit breach"})
    monkeypatch.setattr(kro, "_tick_size_for", lambda s: 0.05)
    kro.place_real_short_stop_loss("X-EQ", 1, 118.0)
    assert all(c > 109.8 * 1.005 for c in calls)


def test_classify_rejection():
    c = kro.classify_rejection
    assert c("login failed: timeout") == "transient"
    assert c("order 1 rejected: Order price is outside the valid price range") == "price_band"
    assert c("order 1 rejected: RMS: T1 holdings cannot be sold") == "t1"
    assert c("order 1 rejected: Insufficient margin") == "margin"
    assert c("order 1 rejected: something new") == "unknown"


def test_retry_wrapper_never_resends_a_rejection(monkeypatch):
    import main
    calls = []
    monkeypatch.setattr(kro, "place_real_stop_loss",
                        lambda *a: calls.append(a) or {"ok": False, "detail": "order 1 rejected: something new"})
    r = main._place_real_stop_loss_with_retry("X-EQ", 1, 95.0, attempts=3)
    assert len(calls) == 1 and r["rejection_kind"] == "unknown"


def test_retry_wrapper_retries_transient(monkeypatch):
    import main
    calls = []
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(kro, "place_real_short_stop_loss",
                        lambda *a: calls.append(a) or {"ok": False, "detail": "place_order raised: reset"})
    main._place_real_stop_loss_with_retry_short("X-EQ", 1, 105.0, attempts=3)
    assert len(calls) == 3


def test_every_rejection_carries_its_kind_and_unknown_alarms(capsys):
    r = kro._rejected_result("7", {"detail": "brand new reason", "row": {}}, {})
    assert r["rejection_kind"] == "unknown" and not r["ok"]
    assert "[ALARM]" in capsys.readouterr().out
    r = kro._rejected_result("8", {"detail": "Circuit breach", "row": {}}, {})
    assert r["rejection_kind"] == "price_band"
    src = open("kotak_real_orders.py").read() + open("kotak_real_fo_orders.py").read()
    assert src.count("rejected: {status['detail']}") == 1  # only inside _rejected_result
