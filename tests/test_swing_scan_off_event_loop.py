import inspect
import main


def test_scheduler_tick_runs_swing_scan_in_thread():
    src = inspect.getsource(main._scheduler_tick)
    assert "asyncio.to_thread(_run_swing_scan_own_conn)" in src
    assert "_run_swing_scan(conn)" not in src


def test_own_conn_wrapper_calls_scan(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "_run_swing_scan", lambda c: seen.setdefault("c", c) and None)
    main._run_swing_scan_own_conn()
    assert "c" in seen
