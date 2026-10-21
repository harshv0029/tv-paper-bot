import main
import nse_fo_chain


def _run(monkeypatch, bid, ask):
    import kotak_real_fo_orders
    seen = []
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity",
                        lambda c: {"bid": bid, "ask": ask, "open_interest": None, "volume": None})
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1000000.0)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {
        "ok": True, "real_pnl_today": 0.0, "cap_inr": 100000.0, "day_open_capital_inr": 1000000.0, "detail": None})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: seen.append(a[3]))
    monkeypatch.setattr(kotak_real_fo_orders, "check_margin_affordable", lambda **k: {"ok": False, "detail": "stop"})
    contract = {"lot_size": 75, "premium": 10.0, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1, "instrument_token": "1"}
    main._real_fo_buy_contract(None, "k", "NIFTY", contract, "t", "strategy", "r")
    return seen


def test_wide_spread_skips_entry(monkeypatch):
    assert _run(monkeypatch, 9.0, 11.0) == ["skipped_spread_too_wide"]  # 20% of mid


def test_tight_spread_passes_through(monkeypatch):
    assert _run(monkeypatch, 9.95, 10.05) == ["skipped_margin_unaffordable"]


def test_unread_quote_does_not_block(monkeypatch):
    assert _run(monkeypatch, None, None) == ["skipped_margin_unaffordable"]
