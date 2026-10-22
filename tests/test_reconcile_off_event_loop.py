"""B-1340: the in-tick unprotected backcheck must not run on the event loop (22 Oct: an inline stall starved the scan)."""
import inspect

import main


def test_scheduler_tick_runs_reconcile_in_worker_thread():
    src = inspect.getsource(main._scheduler_tick)
    assert "asyncio.to_thread(_reconcile_real_positions_core" in src
    assert "\n            _reconcile_real_positions_core(adopt=" not in src
