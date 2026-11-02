"""B-1363 (2026-11-02): every overnight holding's SL must rest at Kotak before 09:16 IST. The dedicated open-protect
thread arms at 09:14:55 IST, fires at 09:15:00.5 and places the missing SLs in parallel."""
import datetime as dt
import threading
import time as _time

import kotak_neo
import main

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(h, m, s=0, us=0, day=2):  # 2026-11-02 is a Monday
    return dt.datetime(2026, 11, day, h, m, s, us, tzinfo=IST)


class _Clock:
    """Fake IST clock; sleep() advances it."""

    def __init__(self, start):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, secs):
        self.slept.append(round(secs, 3))
        self.now += dt.timedelta(seconds=secs)


def test_arms_at_091455_before_open():
    assert main._open_protect_next_arm(_t(8, 0)) == _t(9, 14, 55)
    assert main._open_protect_next_arm(_t(9, 14, 54)) == _t(9, 14, 55)


def test_restart_inside_window_protects_immediately():
    assert main._open_protect_next_arm(_t(9, 16, 30)) == _t(9, 16, 30)


def test_after_window_and_weekend_roll_to_next_weekday():
    assert main._open_protect_next_arm(_t(9, 20)) == _t(9, 14, 55, day=3)
    assert main._open_protect_next_arm(_t(10, 0, day=6)) == _t(9, 14, 55, day=9)  # Friday -> Monday
    assert main._open_protect_next_arm(_t(8, 0, day=7)) == _t(9, 14, 55, day=9)  # Saturday -> Monday


def test_prearm_before_open_then_place_at_091500_and_unpin(monkeypatch):
    clock = _Clock(_t(9, 14, 55))
    order = []
    unpinned = []
    monkeypatch.setattr(kotak_neo, "unpin_order_session", lambda: unpinned.append(True))

    def prearm():
        order.append(("prearm", clock()))
        return {"holdings": {}, "rows": []}

    def place(plan):
        order.append(("place", clock()))
        return {"ok": True, "pending": ["A-EQ"], "failed": []}

    out = main._open_protect_run(now_fn=clock, sleep=clock.sleep, prearm=prearm, place=place)
    assert [o[0] for o in order] == ["prearm", "place"]
    assert order[0][1] < _t(9, 15)
    assert _t(9, 15) <= order[1][1] < _t(9, 15, 1)  # first placement in the opening second, never later
    assert out["ok"] and out["attempts"] == 1 and unpinned


def test_retries_every_3s_until_covered(monkeypatch):
    clock = _Clock(_t(9, 14, 55))
    monkeypatch.setattr(kotak_neo, "unpin_order_session", lambda: None)
    calls = []

    def place(plan):  # exchange rejects the first two (e.g. open not yet live), third lands
        calls.append(clock())
        return {"ok": len(calls) >= 3, "failed": [] if len(calls) >= 3 else ["A-EQ"]}

    out = main._open_protect_run(now_fn=clock, sleep=clock.sleep,
                                 prearm=lambda: {"holdings": {}, "rows": []}, place=place)
    assert out["ok"] and out["attempts"] == 3
    assert [(b - a).total_seconds() for a, b in zip(calls, calls[1:])] == [3.0, 3.0]
    assert calls[-1] < _t(9, 15, 10)


def test_gives_up_at_0920_with_alarm(monkeypatch, capsys):
    clock = _Clock(_t(9, 14, 55))
    monkeypatch.setattr(kotak_neo, "unpin_order_session", lambda: None)
    out = main._open_protect_run(now_fn=clock, sleep=clock.sleep,
                                 prearm=lambda: {"holdings": {}, "rows": []},
                                 place=lambda plan: {"ok": False, "failed": ["A-EQ"]})
    assert not out["ok"] and clock() >= _t(9, 20)
    assert "UNPROTECTED-ALERT" in capsys.readouterr().out


def test_pending_skips_covered_and_sold_rows(monkeypatch):
    plan = {"holdings": {"A-EQ": {"qty": 2, "symbol": "A", "avg_price": 10.0},
                         "B-EQ": {"qty": 1, "symbol": "B", "avg_price": 10.0},
                         "U-EQ": {"qty": 3, "symbol": "U", "avg_price": 10.0}},
            "rows": [{"symbol": "A.NS", "kotak_trading_symbol": "A-EQ", "qty": 2, "stop": 9.0},
                     {"symbol": "B.NS", "kotak_trading_symbol": "B-EQ", "qty": 1, "stop": 9.0},
                     {"symbol": "G.NS", "kotak_trading_symbol": "G-EQ", "qty": 1, "stop": 9.0}]}  # G: no longer held
    order_rows = [{"trdSym": "B-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending", "nOrdNo": "1",
                   "qty": "1", "trgPrc": "9.0"}]
    pend = main._open_protect_pending(plan, order_rows)
    assert {(p["kind"], p["kotak_trading_symbol"]) for p in pend} == {("swing_row", "A-EQ"), ("holding", "U-EQ")}


def test_places_all_missing_sls_in_parallel(monkeypatch):
    import kotak_real_orders

    n = 5
    plan = {"holdings": {f"S{i}-EQ": {"qty": 1, "symbol": f"S{i}", "avg_price": 100.0} for i in range(n)},
            "rows": [{"symbol": f"S{i}.NS", "kotak_trading_symbol": f"S{i}-EQ", "qty": 1, "stop": 90.0}
                     for i in range(n)]}
    monkeypatch.setattr(kotak_neo, "order_report", lambda *a, **k: {"data": []})
    active, peak, lock = [0], [0], threading.Lock()

    def slow_ensure(trd, qty, trg):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _time.sleep(0.3)
        with lock:
            active[0] -= 1
        return {"ok": True, "order_id": f"o-{trd}", "trigger_price": trg, "action": "placed"}

    monkeypatch.setattr(kotak_real_orders, "ensure_resting_sl", slow_ensure)
    logged = []
    monkeypatch.setattr(main, "_log_swing_ensure_sl_result", lambda conn, sym, trd, res, stop, why, **k: logged.append(why))
    monkeypatch.setattr(main, "_heal_real_swing_short_sl", lambda conn, rows: [])
    monkeypatch.setattr(main, "_sync_real_positions_swing_external", lambda conn: None)
    t0 = _time.time()
    out = main._open_protect_place(plan)
    assert out["ok"] and len(out["pending"]) == n
    assert peak[0] == n and _time.time() - t0 < 0.3 * n  # parallel, not 5 x 0.3 s in series
    assert len(logged) == n and all("09:15 IST open protect-first" in w for w in logged)


def test_failed_placement_logged_with_reason(monkeypatch):
    import kotak_real_orders

    plan = {"holdings": {"A-EQ": {"qty": 1, "symbol": "A", "avg_price": 10.0}},
            "rows": [{"symbol": "A.NS", "kotak_trading_symbol": "A-EQ", "qty": 1, "stop": 9.0}]}
    monkeypatch.setattr(kotak_neo, "order_report", lambda *a, **k: {"data": []})
    monkeypatch.setattr(kotak_real_orders, "ensure_resting_sl",
                        lambda *a: {"ok": False, "detail": "RMS: market not open"})
    events = []
    monkeypatch.setattr(main, "_log_real_order_event", lambda conn, sym, leg, ev, **k: events.append((sym, ev, k)))
    monkeypatch.setattr(main, "_flag_if_t1_restricted", lambda *a: None)
    monkeypatch.setattr(main, "_heal_real_swing_short_sl", lambda conn, rows: [])
    monkeypatch.setattr(main, "_sync_real_positions_swing_external", lambda conn: None)
    out = main._open_protect_place(plan)
    assert not out["ok"] and out["failed"] == ["A-EQ"]
    assert events and events[0][1] == "failed" and "reason: 09:15 IST open protect-first" in events[0][2]["detail"]


def test_pinned_session_reused_then_expires(monkeypatch):
    monkeypatch.setattr(kotak_neo, "missing_credentials", lambda: [])
    sentinel = object()
    kotak_neo.pin_order_session(sentinel, 60)
    try:
        assert kotak_neo.login() is sentinel
    finally:
        kotak_neo.unpin_order_session()
    kotak_neo.pin_order_session(sentinel, 0)
    assert kotak_neo._pinned_order_client() is None
    kotak_neo.unpin_order_session()


def test_loop_sleeps_to_arm_then_runs(monkeypatch):
    clock = _Clock(_t(8, 0))
    monkeypatch.setattr(kotak_neo, "missing_credentials", lambda: [])
    ran = []
    main._open_protect_loop(now_fn=clock, sleep=clock.sleep, rounds=1,
                            run=lambda now_fn, sleep: ran.append(now_fn()))
    assert ran == [_t(9, 14, 55)]
