"""B-1316: a real option BUY is skipped unless its initial protective SL is placeable."""
import main
import nse_fo_chain
import kotak_real_fo_orders as k


def test_normal_premium_placeable():
    ok, why = k.option_entry_sl_placeable(100.0, 3.0, bid=99.9)
    assert ok, why  # trigger 97.0, limit 92.15


def test_sub_tick_stop_rounds_onto_entry():
    # 3% of 0.60 = 0.018 < half a tick -> the trigger rounds back onto the 0.60 entry
    ok, why = k.option_entry_sl_placeable(0.60, 3.0)
    assert not ok and "within a tick" in why


def test_trigger_at_or_above_bid_not_placeable():
    # JIOFIN 217.5 CE class: 2.54 x 0.97 = 2.4638 -> trigger 2.45; a bid at 2.45 fires (or is rejected) at once
    ok, why = k.option_entry_sl_placeable(2.54, 3.0, bid=2.45)
    assert not ok and "not below market" in why
    ok, _ = k.option_entry_sl_placeable(2.54, 3.0, bid=2.50)
    assert ok


def test_penny_premium_limit_floors():
    ok, _ = k.option_entry_sl_placeable(0.10, 50.0)
    assert not ok  # trigger 0.05; the limit would floor to 0.05 == trigger


def test_zero_or_negative():
    assert not k.option_entry_sl_placeable(0, 3.0)[0]
    assert not k.option_entry_sl_placeable(5.0, 100.0)[0]


def test_lower_band():
    assert not k.option_entry_sl_placeable(100.0, 3.0, lower_band=95.0)[0]
    assert k.option_entry_sl_placeable(100.0, 3.0, lower_band=90.0)[0]


def _run(monkeypatch, bid, ask, premium):
    seen = []
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity",
                        lambda c: {"bid": bid, "ask": ask, "open_interest": None, "volume": None})
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1000000.0)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {
        "ok": True, "real_pnl_today": 0.0, "cap_inr": 100000.0, "day_open_capital_inr": 1000000.0, "detail": None})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **kw: seen.append(a[3]))
    monkeypatch.setattr(k, "check_margin_affordable", lambda **kw: {"ok": False, "detail": "stop"})

    def _no_buy(*a, **kw):
        raise AssertionError("must not buy")
    monkeypatch.setattr(k, "place_real_fo_entry", _no_buy)
    monkeypatch.setattr(main, "FO_OPTION_MIN_STOP_TICKS", 0)  # isolate B-1316 from the B-1310 tick gate
    contract = {"lot_size": 75, "premium": premium, "kotak_trading_symbol": "X", "exchange_segment": "nse_fo",
                "expiry": "e", "strike": 1, "instrument_token": "1"}
    main._real_fo_buy_contract(None, "k", "NIFTY", contract, "t", "strategy", "r")
    return seen


def test_entry_skipped_when_stop_not_placeable(monkeypatch):
    assert _run(monkeypatch, None, None, premium=0.60) == ["skipped_option_stop_not_placeable"]


def test_entry_proceeds_when_placeable(monkeypatch):
    assert _run(monkeypatch, 99.95, 100.05, premium=100.0) == ["skipped_margin_unaffordable"]
