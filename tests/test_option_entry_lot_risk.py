import main


def test_lot_risk_over_budget_blocks(monkeypatch):
    # B-1310: premium raised from JIOFIN's 2.54 (now blocked earlier by the stop-inside-ticks gate) to keep testing lot risk
    calls = []
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 100000.0)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {
        "ok": True, "real_pnl_today": -91.0, "cap_inr": 130.0, "day_open_capital_inr": 100000.0, "detail": None})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: calls.append(a[3]))
    contract = {"lot_size": 2350, "premium": 6.0, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1}
    main._real_fo_buy_contract(None, "k", "JIOFIN", contract, "universal_score", "strategy", "t")
    assert calls == ["skipped_entry_risk_over_loss_budget"]


def test_lots_shrink_to_fit_loss_budget(monkeypatch):
    """B-1323: risk uses stop 3% + SL-limit offset 5% = 8% of the lot, and lots shrink to fit instead of skipping."""
    import kotak_real_fo_orders
    seen = {}
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1000000.0)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {
        "ok": True, "real_pnl_today": 0.0, "cap_inr": 1000.0, "day_open_capital_inr": 1000000.0, "detail": None})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: seen.update(event=a[3], qty=k.get("qty")))
    monkeypatch.setattr(kotak_real_fo_orders, "check_margin_affordable", lambda **k: {"ok": False, "detail": "stop here"})
    contract = {"lot_size": 100, "premium": 10.0, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1, "instrument_token": "1"}
    main._real_fo_buy_contract(None, "k", "NIFTY", contract, "universal_score", "strategy", "t", budget_inr=1000000.0)
    # unit risk = 100 x 10 x 8% = 80; budget left 1000 -> 12 lots
    assert seen == {"event": "skipped_margin_unaffordable", "qty": 1200}
