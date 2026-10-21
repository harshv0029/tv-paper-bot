import main


def test_lot_risk_over_budget_blocks(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 100000.0)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {
        "ok": True, "real_pnl_today": -91.0, "cap_inr": 130.0, "day_open_capital_inr": 100000.0, "detail": None})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: calls.append(a[3]))
    contract = {"lot_size": 2350, "premium": 2.54, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1}
    main._real_fo_buy_contract(None, "k", "JIOFIN", contract, "universal_score", "strategy", "t")
    assert calls == ["skipped_entry_risk_over_loss_budget"]
