"""B-1651: positions with their exit due today carry a deadline timestamp and an on-time / late verdict."""
import datetime as dt
import time
from contextlib import closing

import main


def _setup(monkeypatch, now):
    main.init_db()
    monkeypatch.setattr(main, "ist_now", lambda: now)
    monkeypatch.setattr(main, "_exit_timing_push", lambda: None)
    main._exit_timing.update(day="", rows={})
    with closing(main.get_db()) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short", "real_fo_positions"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM real_order_events")
        c.commit()


def _open_buy(sym, day):
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                  "VALUES (?, ?, 1, 100.0, ?, ?)", (sym, sym.replace(".NS", "-EQ"), time.time() - 3600, day))
        c.commit()


def _close(sym):
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_positions WHERE symbol = ?", (sym,))
        c.commit()


def test_intraday_due_today_tracked_then_exited_on_time(monkeypatch):
    now = dt.datetime.combine(dt.date(2026, 11, 20), dt.time(15, 0))
    _setup(monkeypatch, now)
    _open_buy("ABC.NS", "2026-11-20")
    with closing(main.get_db()) as c:
        assert main._exit_timing_sweep(c, now) == {"pending": 1}
    e = main._exit_timing_for("buy", "ABC.NS")
    assert e["exit_deadline_ist"] == "2026-11-20 15:14:00 IST" and e["status"] == "pending"
    _close("ABC.NS")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, now + dt.timedelta(minutes=10))
    e = main._exit_timing_for("buy", "ABC.NS")
    assert e["status"] == "exited_on_time" and e["exited_at_ist"].startswith("2026-11-20 15:10")
    assert main.exit_timing_today()["counts"] == {"exited_on_time": 1}


def test_intraday_still_open_past_deadline_is_overdue_and_logged(monkeypatch):
    now = dt.datetime.combine(dt.date(2026, 11, 20), dt.time(15, 25))
    _setup(monkeypatch, now)
    monkeypatch.setattr(main, "_nse_closed_day", lambda *a, **k: False)
    _open_buy("LATE.NS", "2026-11-20")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, now)
        ev = c.execute("SELECT leg, event FROM real_order_events WHERE symbol = 'LATE.NS'").fetchall()
    e = main._exit_timing_for("buy", "LATE.NS")
    assert e["status"] == "overdue" and e["late_min"] == 11.0
    assert [tuple(x) for x in ev] == [("audit", "exit_overdue")]
    _close("LATE.NS")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, now + dt.timedelta(minutes=1))
    e = main._exit_timing_for("buy", "LATE.NS")
    assert e["status"] == "exited_late" and e["late_min"] == 12.0


def test_exit_time_taken_from_confirmed_exit_order(monkeypatch):
    now = dt.datetime.combine(dt.date(2026, 11, 20), dt.time(14, 0))
    _setup(monkeypatch, now)
    _open_buy("EV.NS", "2026-11-20")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, now)
        # confirmed exit at 14:05 IST, detected by the sweep only at 15:30 IST
        ts = (dt.datetime(2026, 11, 20, 14, 5) - dt.timedelta(minutes=main.IST_OFFSET_MIN)).replace(
            tzinfo=dt.timezone.utc).timestamp()
        main._log_real_order_event(c, "EV.NS", "exit", "confirmed", reason="t")
        c.execute("UPDATE real_order_events SET ts = ? WHERE symbol = 'EV.NS'", (ts,))
        c.commit()
    _close("EV.NS")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, dt.datetime(2026, 11, 20, 15, 30))
    e = main._exit_timing_for("buy", "EV.NS")
    assert e["status"] == "exited_on_time" and e["exited_at_ist"] == "2026-11-20 14:05:00 IST"
    assert e["exit_source"] == "exit order confirmed"


def test_swing_deadline_is_1510_on_exit_day_and_future_days_not_tracked():
    d = main._exit_timing_deadline("swing", {"expected_exit": "2026-11-20"})
    assert d == (dt.datetime(2026, 11, 20, 15, 10), 0)
    assert main._exit_timing_deadline("buy", {"expected_exit": "2026-11-20 15:14 IST"})[1] == 5
    assert main._exit_timing_deadline("swing", {"expected_exit": None}) is None


def test_restore_on_wipe_from_upstash(monkeypatch):
    import json
    now = dt.datetime.combine(dt.date(2026, 11, 20), dt.time(11, 0))
    monkeypatch.setattr(main, "ist_now", lambda: now)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    row = {"symbol": "R.NS", "category": "swing", "status": "overdue", "exit_deadline_ist": "2026-11-19 15:10:00 IST"}
    store = {main._EXIT_TIMING_REDIS_KEY: json.dumps({"day": "2026-11-20", "rows": {"swing|R.NS": row}})}
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    main._exit_timing.update(day="", rows={})  # Render disk wiped / restart
    assert main.hydrate_exit_timing_from_external() == 1
    assert main._exit_timing_for("swing", "R.NS")["status"] == "overdue"
    store[main._EXIT_TIMING_REDIS_KEY] = json.dumps({"day": "2026-11-19", "rows": {"swing|Q.NS": row}})
    main._exit_timing.update(day="", rows={})
    assert main.hydrate_exit_timing_from_external() == 0  # an earlier IST day is ignored


def _open_fo(leg, underlying, expiry, strike=100.0, seg="nse_fo", tag="fo_test", opened_at=None):
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_fo_positions")
        c.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, "
                  "instrument_token, exchange_segment, expiry, strike, lot_size, qty, entry_price, opened_at, day) "
                  "VALUES (?, ?, ?, ?, '1', ?, ?, ?, 1, 1, 10.0, ?, '2026-11-20')",
                  (leg, underlying, tag, leg + "TS", seg, expiry, strike, opened_at or time.time()))
        c.commit()


def test_fo_cash_settled_option_due_on_expiry_day(monkeypatch):
    now = dt.datetime.combine(dt.date(2026, 11, 24), dt.time(11, 0))
    _setup(monkeypatch, now)
    _open_fo("NIFTY:CALL", "NIFTY", "2026-11-24")
    with closing(main.get_db()) as c:
        main._exit_timing_sweep(c, now)
    e = main._exit_timing_for("options", "NIFTY:CALL")
    assert e["exit_deadline_ist"] == "2026-11-24 15:10:00 IST" and e["symbol"] == "NIFTY:CALLTS"
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_fo_positions")
        c.commit()
        main._exit_timing_sweep(c, now + dt.timedelta(minutes=5))
    assert main._exit_timing_for("options", "NIFTY:CALL")["status"] == "exited_on_time"


def test_fo_physically_settled_stock_due_two_days_before_expiry_and_mcx_evening(monkeypatch):
    import nse_fo_chain
    now = dt.datetime.combine(dt.date(2026, 11, 24), dt.time(10, 0))
    _setup(monkeypatch, now)
    monkeypatch.setattr(nse_fo_chain, "is_physically_settled", lambda u: u == "RELIANCE")
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: d is None or d.weekday() < 5)
    with closing(main.get_db()) as c:
        r = main._exit_timing_fo_row(c, {"leg_key": "RELIANCE:CALL", "underlying": "RELIANCE", "expiry": "2026-11-26",
                                         "strike": 1300.0, "exchange_segment": "nse_fo", "strategy_tag": "x"})
        assert r["deadline"] == (dt.datetime(2026, 11, 24, 15, 10), 0) and r["category"] == "options"
        m = main._exit_timing_fo_row(c, {"leg_key": "CRUDEOIL:FUT", "underlying": "CRUDEOIL", "expiry": "2026-11-24",
                                         "strike": None, "exchange_segment": "mcx_fo", "strategy_tag": "x"})
        assert m["deadline"] == (dt.datetime(2026, 11, 24, 23, 20), 0) and m["category"] == "commodity"


def test_nse_add_market_hours_inverts_market_hours_between(monkeypatch):
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: d is None or d.weekday() < 5)
    monkeypatch.setattr(main, "nse_special_session", lambda d: None)
    start = dt.datetime(2026, 11, 20, 14, 0)  # Friday
    end = main._nse_add_market_hours(start, 6.25)
    assert end == dt.datetime(2026, 11, 23, 14, 0)  # 1.5 h Fri + 4.75 h Mon
    assert abs(main._nse_market_hours_between(start, end) - 6.25) < 1e-9
