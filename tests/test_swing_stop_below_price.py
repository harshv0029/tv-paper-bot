"""DABUR 2026-10-08: a swing stop at/above the market became a limit sell, leaving no real stop."""
import main
import kotak_real_orders as kro


def test_valid_stop_unchanged():
    assert main._swing_stop_below_price(375.0, 379.05) == 375.0


def test_stop_above_price_reset_below_market():
    assert main._swing_stop_below_price(380.25, 379.05) == round(379.05 * 0.99, 2)
    assert main._swing_stop_below_price(379.05, 379.05) < 379.05


def test_cancel_converted_only_matches_stale_limit_sell(monkeypatch):
    rows = [
        {"trdSym": "DABUR-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open", "prc": "380.25", "nOrdNo": "1"},
        {"trdSym": "DABUR-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open", "prc": "395.00", "nOrdNo": "2"},
        {"trdSym": "DABUR-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "open", "prc": "380.25", "nOrdNo": "3"},
        {"trdSym": "DABUR-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "complete", "prc": "380.25", "nOrdNo": "4"},
    ]

    class C:
        def order_report(self): return {"data": rows}
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: C())
    cancelled = []
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: cancelled.append(oid) or {"ok": True})
    assert kro.cancel_converted_stop_orders("DABUR-EQ", 380.25) == ["1"]
    assert cancelled == ["1"]
