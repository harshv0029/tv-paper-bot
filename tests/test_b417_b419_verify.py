"""2026-10-12 IST verification tests for B-417 (swing option leg SL), B-419 (forming bar dropped), B-817 (exit remark gaps)."""
import os, tempfile
from contextlib import closing
import pandas as pd
import pytest
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()


CONTRACT = {"kotak_trading_symbol": "TCS26OCT4000CE", "instrument_token": "1", "exchange_segment": "nse_fo",
            "expiry": "2099-01-01", "strike": 4000, "lot_size": 175, "premium": 100.0}


def _patch_buy(monkeypatch, sl_status, closed):
    import kotak_real_fo_orders as kfo
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1e9)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {"ok": True, "real_pnl_today": 0.0, "detail": ""})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: None)
    monkeypatch.setattr(kfo, "check_margin_affordable", lambda **k: {"ok": True})
    monkeypatch.setattr(kfo, "place_real_fo_entry", lambda *a, **k: {"ok": True, "order_id": "E1"})
    monkeypatch.setattr(main, "_sync_real_fo_option_sl", lambda conn, leg, reason="": sl_status)
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, why: closed.append(why))


def test_b417_entry_attaches_initial_sl_right_after_fill(monkeypatch):
    _db(); closed = []
    _patch_buy(monkeypatch, "placed", closed)
    with closing(main.get_db()) as c:
        main._real_fo_buy_contract(c, "TCS:CALL", "TCS", dict(CONTRACT), "single_leg_swing_call", "single_leg_swing_call", "t")
        row = c.execute("SELECT strategy_tag FROM real_fo_positions WHERE leg_key='TCS:CALL'").fetchone()
    assert row[0] == "single_leg_swing_call" and not closed


def test_b417_entry_unwound_when_sl_cannot_be_placed(monkeypatch):
    """No trade without SL: SL failure right after the fill closes the leg immediately."""
    _db(); closed = []
    _patch_buy(monkeypatch, "sl_failed", closed)
    monkeypatch.setattr(main, "FO_ENTRY_SL_FAIL_RETRY_WINDOW_S", 0.0)
    with closing(main.get_db()) as c:
        main._real_fo_buy_contract(c, "TCS:CALL", "TCS", dict(CONTRACT), "single_leg_swing_call", "single_leg_swing_call", "t")
    assert closed and "entry unwound" in closed[0]


def test_b1318_failed_entry_sl_is_retried_before_unwind(monkeypatch):
    """A transient first SL failure is retried within the window; a later success keeps the position."""
    _db(); closed = []; calls = []
    _patch_buy(monkeypatch, "sl_failed", closed)
    def _sl(conn, leg, reason=""):
        calls.append(reason)
        return "sl_failed" if len(calls) < 3 else "placed"
    monkeypatch.setattr(main, "_sync_real_fo_option_sl", _sl)
    monkeypatch.setattr(main, "FO_ENTRY_SL_FAIL_RETRY_SLEEP_S", 0.0)
    with closing(main.get_db()) as c:
        main._real_fo_buy_contract(c, "TCS:CALL", "TCS", dict(CONTRACT), "single_leg_swing_call", "single_leg_swing_call", "t")
    assert len(calls) == 3 and not closed


def _sync(monkeypatch, entry, peak, ltp):
    import kotak_real_fo_orders as kfo, time
    _db()
    placed = {}
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, exchange_segment, "
                  "expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, peak_price) "
                  "VALUES ('TCS:CALL','TCS','single_leg_swing_call','TCS26OCT4000CE','1','nse_fo','2099-01-01',4000,175,175,?, 'E',?, 'd', ?)",
                  (entry, time.time() - 1000, peak))
        c.commit()
        monkeypatch.setattr(kfo, "fetch_kotak_option_state", lambda s: {"ok": True, "net_qty": 175, "live_sls": []})
        monkeypatch.setattr(kfo, "ensure_option_trailing_sl", lambda sym, seg, q, trig, live: placed.update(trig=trig) or
                            {"ok": True, "order_id": "S1", "trigger_price": trig, "action": "placed"})
        monkeypatch.setattr(main, "_option_ltp", lambda r: ltp)
        monkeypatch.setattr(main, "kotak_real_orders_closing_session", lambda: False)
        import nse_fo_chain
        monkeypatch.setattr(nse_fo_chain, "must_force_close_before_expiry", lambda u, e: False)
        monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: None)
        main._sync_real_fo_option_sl(c, "TCS:CALL")
    return placed["trig"]


def test_b417_initial_stop_below_entry_then_trails_up(monkeypatch):
    t0 = _sync(monkeypatch, 100.0, 100.0, 100.0)
    assert t0 == pytest.approx(100.0 * (1 - main.FO_OPTION_INITIAL_STOP_PCT / 100.0))
    t1 = _sync(monkeypatch, 100.0, 130.0, 130.0)
    assert t1 == pytest.approx(130.0 * (1 - main.FO_OPTION_TRAIL_PCT / 100.0)) and t1 > t0


def test_b417_swing_short_mirror_has_no_put_leg():
    """Documents the OWED gap: only a CALL leg exists for swing entries (no PE on a swing short mirror)."""
    import inspect
    src = inspect.getsource(main._maybe_place_swing_option_leg)
    assert '"call"' in src and '"put"' not in src


def test_b419_forming_daily_bar_dropped_while_market_open(monkeypatch):
    _db()
    today = main.ist_now().strftime("%Y-%m-%d")
    idx = pd.to_datetime([pd.Timestamp(today) - pd.Timedelta(days=59 - i) for i in range(60)])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    assert str(df.index[-1])[:10] == today

    class Stop(BaseException):
        pass
    seen = {}

    def cap(closes):
        seen.update({k: len(v) for k, v in closes.items()})
        raise Stop()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["X.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: df)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: False)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 1e5)
    monkeypatch.setattr(main, "_record_swing_check", lambda s: None)
    monkeypatch.setattr(main, "_compute_minervini_rs_percentiles", cap)
    for open_now, expect in ((True, 59), (False, 60)):
        monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda o=open_now: o)
        seen.clear()
        with closing(main.get_db()) as c, pytest.raises(Stop):
            main._run_swing_scan_pass(c)
        assert seen["X.NS"] == expect


def test_b817_kotak_buy_fill_overrides_app_entry_and_sl_from_app_row():
    _db(); day = main.ist_now().strftime("%d-%b-%Y")
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_swing (symbol,kotak_trading_symbol,qty,entry_price,opened_at,day,stop_loss,sl_trigger_price) "
                  "VALUES ('Z.NS','Z-EQ',10,999,1,'d',90,91)")
        c.commit()
        rows = [{"nOrdNo": "1", "trdSym": "Z-EQ", "trnsTp": "B", "ordSt": "complete", "fldQty": "10", "avgPrc": "100", "ordDtTm": f"{day} 09:20:00"},
                {"nOrdNo": "2", "trdSym": "Z-EQ", "trnsTp": "S", "ordSt": "complete", "fldQty": "10", "avgPrc": "90.5", "ordDtTm": f"{day} 11:00:00", "prcTp": "SL-M"}]
        out = main._kotak_exit_fills_today(rows, set(), c)
    assert out[0]["entry_price_native"] == 100.0                  # Kotak BUY fill, not app 999
    assert out[0]["exit_kind"] == "stop_loss_triggered_at_kotak"  # SL-M with no trgPrc falls back to app SL level
    assert "trigger 91.00" in out[0]["exit_remark"] and "loss 9.50%" in out[0]["exit_remark"]


def test_b817_short_cover_buy_fills_not_listed_known_gap():
    """Documents the OWED gap: only SELL fills are listed, so a short cover (BUY) gets no remark row."""
    _db(); day = main.ist_now().strftime("%d-%b-%Y")
    with closing(main.get_db()) as c:
        rows = [{"nOrdNo": "3", "trdSym": "W-EQ", "trnsTp": "B", "ordSt": "complete", "fldQty": "10", "avgPrc": "50", "ordDtTm": f"{day} 12:00:00", "prcTp": "SL"}]
        assert main._kotak_exit_fills_today(rows, set(), c) == []


def test_b1320_unreadable_kotak_with_no_sl_is_risk_cut_after_window(monkeypatch):
    import kotak_real_fo_orders as kfo, time
    _db(); closed = []
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, exchange_segment, "
                  "expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, peak_price) "
                  "VALUES ('TCS:CALL','TCS','single_leg_swing_call','TCS26OCT4000CE','1','nse_fo','2099-01-01',4000,175,175,100,'E',?, 'd', 100)",
                  (time.time() - 1000,))
        c.commit()
        monkeypatch.setattr(kfo, "fetch_kotak_option_state", lambda s: {"ok": False, "detail": "down"})
        monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, why: closed.append(why))
        main._fo_sl_unprotected_since.pop("TCS:CALL", None)
        assert main._sync_real_fo_option_sl(c, "TCS:CALL").startswith("kotak_unreadable") and not closed
        main._fo_sl_unprotected_since["TCS:CALL"] = time.time() - main.FO_OPTION_SL_FAIL_EXIT_SECONDS - 1
        assert main._sync_real_fo_option_sl(c, "TCS:CALL") == "risk_cut_exit" and closed


def test_b1321_premium_below_sl_limit_is_market_exited(monkeypatch):
    import kotak_real_fo_orders as kfo, time
    _db(); closed = []
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, exchange_segment, "
                  "expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, peak_price, sl_trigger_price) "
                  "VALUES ('TCS:CALL','TCS','single_leg_swing_call','TCS26OCT4000CE','1','nse_fo','2099-01-01',4000,175,175,100,'E',?, 'd', 100, 97)",
                  (time.time() - 1000,))
        c.commit()
        monkeypatch.setattr(kfo, "fetch_kotak_option_state", lambda s: {"ok": True, "net_qty": 175, "live_sls": []})
        monkeypatch.setattr(main, "_option_ltp", lambda r: 90.0)  # 97 * 0.95 = 92.15 > 90
        monkeypatch.setattr(main, "_option_feed_high_since", lambda conn, r: None)
        monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, why: closed.append(why))
        import nse_fo_chain
        monkeypatch.setattr(nse_fo_chain, "must_force_close_before_expiry", lambda u, e: False)
        assert main._sync_real_fo_option_sl(c, "TCS:CALL") == "gap_through_exit" and closed
