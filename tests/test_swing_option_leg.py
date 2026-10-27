import sqlite3, main


def _conn():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE real_fo_positions (leg_key TEXT PRIMARY KEY, strategy_tag TEXT, kotak_trading_symbol TEXT, qty INT, opened_at REAL)")
    return c


def test_underlying_only_for_fo_stocks():
    assert main._swing_option_underlying("TCS.NS") == "TCS"
    assert main._swing_option_underlying("NOTASTOCK.NS") is None


def test_entry_buys_call_with_swing_tag(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "is_real_fo_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda t: True)
    monkeypatch.setattr(main, "SWING_REAL_ENTRY_CUTOFF_MIN", 24 * 60)
    import kotak_live_feed, nse_fo_chain
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: {"TCS.NS": {"ltp": 4000.0}})
    monkeypatch.setattr(nse_fo_chain, "select_nse_option_contract", lambda u, s, r, expiry_ok=None: ({"expiry": "2099-01-01", "premium": 50.0, "lot_size": 175}, None))
    monkeypatch.setattr(nse_fo_chain, "must_force_close_before_expiry", lambda u, e: False)
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity", lambda c: {"bid": 49.5, "ask": 50.5, "open_interest": 1e6, "volume": 1e5})
    monkeypatch.setattr(main, "_real_fo_buy_contract", lambda *a, **k: calls.append(a))
    main._maybe_place_swing_option_leg(_conn(), "TCS.NS", "gap_and_go")
    assert calls and calls[0][1] == "TCS:CALL" and calls[0][5] == "single_leg_swing_call"


def test_entry_skipped_and_logged_when_illiquid_or_data_missing(monkeypatch):
    calls, logs = [], []
    monkeypatch.setattr(main, "is_real_fo_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda t: True)
    monkeypatch.setattr(main, "SWING_REAL_ENTRY_CUTOFF_MIN", 24 * 60)
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: logs.append((a, k)))
    import kotak_live_feed, nse_fo_chain
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: {"TCS.NS": {"ltp": 4000.0}})
    monkeypatch.setattr(nse_fo_chain, "select_nse_option_contract", lambda u, s, r, expiry_ok=None: ({"expiry": "2099-01-01", "premium": 50.0, "lot_size": 175}, None))
    monkeypatch.setattr(nse_fo_chain, "must_force_close_before_expiry", lambda u, e: False)
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity", lambda c: {"bid": None, "ask": None, "open_interest": None, "volume": None})
    monkeypatch.setattr(main, "_real_fo_buy_contract", lambda *a, **k: calls.append(a))
    main._maybe_place_swing_option_leg(_conn(), "TCS.NS", "gap_and_go")
    assert not calls and logs[-1][0][3] == "skipped_illiquid_stock_option"


def test_entry_blocked_when_not_viable_or_already_open(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "is_real_fo_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: None)
    monkeypatch.setattr(main, "_real_fo_buy_contract", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda t: False)
    main._maybe_place_swing_option_leg(_conn(), "TCS.NS", "x")
    assert not calls


def test_exit_only_closes_swing_owned_leg(monkeypatch):
    closed = []
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda c, r, why: closed.append((r["leg_key"], why)))
    c = _conn()
    c.execute("INSERT INTO real_fo_positions VALUES ('TCS:CALL','single_leg_call','S',1,0)")
    main._close_swing_option_leg(c, "TCS.NS", "stop")
    assert not closed
    c.execute("UPDATE real_fo_positions SET strategy_tag='single_leg_swing_call'")
    main._close_swing_option_leg(c, "TCS.NS", "stop")
    assert closed and "swing exit: stop" in closed[0][1]
