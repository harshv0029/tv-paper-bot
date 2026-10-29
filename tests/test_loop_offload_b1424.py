"""B-1424: Kotak / SQLite I/O the watchdog caught on the event loop now runs on worker threads."""
import inspect
import threading

import kotak_fo_candle_feed
import main


def test_scheduler_tick_runs_swing_trail_off_loop():
    src = inspect.getsource(main._scheduler_tick)
    assert "asyncio.to_thread(_swing_ltp_trail_on_thread)" in src
    assert "_sync_swing_ltp_trail(_trail_conn)" not in src


def test_fo_feed_persists_candles_off_loop():
    src = inspect.getsource(kotak_fo_candle_feed.run_fo_candle_feed)
    assert "asyncio.to_thread(process_fo_ticks" in src


def test_swing_trail_helper_uses_own_conn_and_decision_lock(monkeypatch):
    seen = {}

    def fake_trail(conn):
        seen["thread"] = threading.current_thread().name
        seen["locked"] = main._SCAN_DECISION_LOCK.locked()
        seen["conn"] = conn
        return ["ok"]

    monkeypatch.setattr(main, "_sync_swing_ltp_trail", fake_trail)
    assert main._swing_ltp_trail_on_thread() == ["ok"]
    assert seen["locked"] is True
    assert seen["conn"] is not None
    assert not main._SCAN_DECISION_LOCK.locked()


def test_static_callgraph_no_kotak_io_on_loop():
    """No async def in main.py reaches the swing trail or candle persistence without a thread hop."""
    import ast
    tree = ast.parse(inspect.getsource(main))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                    assert call.func.id not in ("_sync_swing_ltp_trail", "process_fo_ticks"), node.name
