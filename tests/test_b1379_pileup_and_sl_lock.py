"""B-1379 (live 2026-10-27): duplicate 09:15 SLs rejected by Kotak RMS, and a thread pile-up before the 09:20 OOM."""
import threading

import kotak_real_orders as kro
import main


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def order_report(self):
        return {"data": self.rows}


def test_second_caller_adopts_sl_placed_seconds_ago(monkeypatch):
    # the order book has not caught up yet (empty), but this process placed an SL 1 s ago
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _Client([]))
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    placed = []

    def fake_unlocked(sym, qty, trg):
        placed.append(trg)
        return {"ok": True, "order_id": f"O{len(placed)}", "trigger_price": trg}
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked", fake_unlocked)
    first = kro.ensure_resting_sl("WIPRO-EQ", 1, 175.12)
    second = kro.ensure_resting_sl("WIPRO-EQ", 1, 175.12)
    assert first["action"] == "placed" and second["action"] == "adopted_existing"
    assert placed == [175.12]


def test_raise_right_after_place_cancels_first(monkeypatch):
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _Client([]))
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    cancelled = []
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: cancelled.append(oid) or {"ok": True})
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked",
                        lambda s, q, t: {"ok": True, "order_id": f"O{t}", "trigger_price": t})
    kro.ensure_resting_sl("COALINDIA-EQ", 2, 373.20)
    res = kro.ensure_resting_sl("COALINDIA-EQ", 2, 398.35)
    assert res["action"] == "replaced" and cancelled == ["O373.2"]


def test_recent_entry_ignored_once_order_book_shows_it(monkeypatch):
    rows = [{"nOrdNo": "O1", "trdSym": "GSEC5IETF-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "rejected",
             "trgPrc": "64.7", "qty": "2"}]
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _Client(rows))
    kro._RECENT_SL_PLACED["GSEC5IETF-EQ"] = {"order_id": "O1", "qty": 2, "trigger": 64.7, "ts": kro.time.time()}
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked",
                        lambda s, q, t: {"ok": True, "order_id": "O2", "trigger_price": t})
    assert kro.ensure_resting_sl("GSEC5IETF-EQ", 2, 64.70)["action"] == "placed"


def test_scan_activity_single_flight_returns_last_result(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_strategy_scan_activity_compute", lambda inc=False: calls.append(1) or {"n": 1})
    main._SCAN_ACTIVITY_CACHE[False] = (0.0, {"n": "stale"})
    assert main._SCAN_ACTIVITY_LOCK.acquire()
    try:
        assert main.strategy_scan_activity(False) == {"n": "stale"}  # compute already running elsewhere
    finally:
        main._SCAN_ACTIVITY_LOCK.release()
    assert calls == []
    assert main.strategy_scan_activity(False) == {"n": 1}
    main._SCAN_ACTIVITY_CACHE.clear()


def test_first_sight_push_failure_is_not_retried_per_call(monkeypatch):
    with main.closing(main.get_db()) as c:
        c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)", (1.0, "x", "[]"))
        c.commit()
    n = {"merge": 0, "push": 0}
    monkeypatch.setattr(main, "_viable_stack_merge_remote", lambda: n.__setitem__("merge", n["merge"] + 1) or 0)
    monkeypatch.setattr(main, "_viable_stack_push_direct", lambda *a, **k: n.__setitem__("push", n["push"] + 1) or False)
    monkeypatch.setitem(main._VIABLE_STACK_MIRROR_STATE, "last_push_ok", None)
    ts = [threading.Thread(target=main._ensure_viable_stack_hydrated) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    main._ensure_viable_stack_hydrated()
    with main.closing(main.get_db()) as c:  # never leave a stack row behind: later tests would see an active stack
        c.execute("DELETE FROM strategy_viable_stack WHERE label = 'x' AND created_at = 1.0")
        c.commit()
    assert n == {"merge": 1, "push": 1}
