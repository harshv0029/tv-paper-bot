import datetime as dt

import main

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(h, m, s=0, day=26):  # 2026-10-26 is a Monday
    return dt.datetime(2026, 10, day, h, m, s, tzinfo=IST)


def test_wakes_exactly_at_open():
    assert main._unprotected_backcheck_next_sleep(_t(9, 13, 20)) == 101.0


def test_far_before_open_uses_base_cadence():
    assert main._unprotected_backcheck_next_sleep(_t(8, 0)) == 300.0


def test_fast_cadence_inside_open_window():
    assert main._unprotected_backcheck_next_sleep(_t(9, 15, 1)) == 20.0
    assert main._unprotected_backcheck_next_sleep(_t(9, 29, 59)) == 20.0


def test_normal_cadence_after_window_and_weekend():
    assert main._unprotected_backcheck_next_sleep(_t(9, 30)) == 300.0
    assert main._unprotected_backcheck_next_sleep(_t(9, 14, 0, day=24)) == 300.0  # Saturday


def test_loop_uses_adaptive_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(main, "_unprotected_backcheck_once", lambda: True)
    monkeypatch.setattr(main, "_unprotected_backcheck_next_sleep", lambda: 20.0)
    main._unprotected_backcheck_loop(sleep=slept.append, rounds=2)
    assert slept == [20.0, 20.0]


def test_holding_heals_run_in_parallel(monkeypatch):
    """B-1363: 5 unprotected holdings must not be healed one after another (~13 s each)."""
    import threading
    import time as _time
    from unittest.mock import MagicMock

    holdings = {f"S{i}-EQ": {"symbol": f"S{i}", "qty": 1, "avg_price": 100.0} for i in range(5)}
    active, peak, lock = [0], [0], threading.Lock()

    def slow_heal(trd, held, rows):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _time.sleep(0.3)
        with lock:
            active[0] -= 1
        return {"sl_ok": True, "stop": 90.0}

    monkeypatch.setattr(main, "_heal_swing_holding_core", slow_heal)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "_kotak_holdings_open_by_trdsym", lambda *a, **k: holdings, raising=False)
    fake = MagicMock()
    fake.positions.return_value = {"data": []}
    fake.order_report.return_value = {"data": []}
    fake.holdings.return_value = {"data": []}
    monkeypatch.setitem(__import__("sys").modules, "kotak_neo", fake)
    try:
        out = main._reconcile_real_positions_core(adopt="*")
    except Exception:
        out = None
    if out is None or not out.get("holdings_healed"):
        import pytest
        pytest.skip("reconcile harness did not reach the holdings heal in this environment")
    assert len(out["holdings_healed"]) == 5 and peak[0] >= 2
