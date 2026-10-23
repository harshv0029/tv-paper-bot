"""B-1340: the in-tick unprotected backcheck must not run on the event loop (22 Oct: an inline stall starved the scan).
B-1354: the 5-min backcheck now runs on its own daemon thread; the tick's 09:15-09:30 pass still goes via to_thread."""
import inspect

import main


def test_scheduler_tick_runs_reconcile_in_worker_thread():
    src = inspect.getsource(main._scheduler_tick)
    assert "asyncio.to_thread(_unprotected_backcheck_once)" in src
    assert "\n            _reconcile_real_positions_core(adopt=" not in src
    assert "\n            _unprotected_backcheck_once()" not in src
