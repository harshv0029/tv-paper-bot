import main
import nse_fo_chain


def _run(monkeypatch, bid, ask, premium=10.0, trail_dist=None):
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
    contract = {"lot_size": 75, "premium": premium, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1, "instrument_token": "1"}
    main._real_fo_buy_contract(None, "k", "NIFTY", contract, "t", "strategy", "r", trail_dist=trail_dist)
    return seen


def test_wide_spread_skips_entry(monkeypatch):
    assert _run(monkeypatch, 9.0, 11.0) == ["skipped_spread_too_wide"]  # 20% of mid


def test_tight_spread_passes_through(monkeypatch):
    assert _run(monkeypatch, 9.95, 10.05) == ["skipped_margin_unaffordable"]


def test_unread_quote_does_not_block(monkeypatch):
    assert _run(monkeypatch, None, None) == ["skipped_margin_unaffordable"]


def test_b1310_penny_premium_stop_inside_ticks_skips(monkeypatch):
    # JIOFIN 217.5 CE, 21 Oct: premium 2.54, 3% stop = 0.076 < 3 ticks of 0.05 -> stopped on the first print
    assert _run(monkeypatch, 2.50, 2.55, premium=2.54) == ["skipped_stop_inside_ticks"]


def test_b1310_spread_wider_than_half_the_stop_skips(monkeypatch):
    # 2% spread is under the 5% cap but more than half of a 3% stop
    assert _run(monkeypatch, 9.9, 10.1) == ["skipped_spread_too_wide"]
    # a wider ATR trail (3% of 10 = 0.3) keeps the same cap; a 1% spread passes
    assert _run(monkeypatch, 9.95, 10.05, trail_dist=0.3) == ["skipped_margin_unaffordable"]
