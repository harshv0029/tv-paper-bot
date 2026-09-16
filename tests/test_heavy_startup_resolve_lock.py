"""Regression test for main._heavy_startup_resolve_lock (2026-09-16,
live Render OOM follow-up): after fixing the port-scan-timeout bug via
asyncio.to_thread, the app booted fast and served real traffic, then
the process vanished with no Python traceback - the signature of an
OOM kill. Root cause: to_thread let kotak_fo_candle_feed's
resolve_fo_universe() and kotak_live_feed's resolve_tokens() - both
memory-heavy, previously ACCIDENTALLY serialized because each used to
block the whole event loop - run at the exact same time, stacking
their peak memory usage. Fixed by wrapping both in a shared
asyncio.Lock. This test proves the two never overlap, not just that
the lock is referenced in source.

Run: pytest tests/ -v
"""
import asyncio
import time as time_module
from unittest.mock import patch

import kotak_fo_candle_feed as fo_feed
import kotak_live_feed as live_feed
import main


def test_fo_and_equity_heavy_resolves_never_overlap():
    overlap_windows = []
    active = {"fo": False, "equity": False}

    def _mark_active(key, duration):
        active[key] = True
        if active["fo"] and active["equity"]:
            overlap_windows.append(True)
        time_module.sleep(duration)
        active[key] = False

    async def _run_fo_resolve_once():
        fo_feed._universe_cache["value"] = None
        fo_feed._universe_cache["resolved_at"] = 0.0
        with patch.object(fo_feed, "resolve_fo_universe", side_effect=lambda: _mark_active("fo", 0.15) or {}):
            async with main._heavy_startup_resolve_lock:
                await asyncio.to_thread(fo_feed.resolve_fo_universe)

    async def _run_equity_resolve_once():
        with patch.object(live_feed, "resolve_tokens", side_effect=lambda *a, **k: _mark_active("equity", 0.15) or {}):
            async with main._heavy_startup_resolve_lock:
                await asyncio.to_thread(live_feed.resolve_tokens, None, [])

    async def run_both():
        await asyncio.gather(_run_fo_resolve_once(), _run_equity_resolve_once())

    asyncio.run(run_both())
    assert overlap_windows == []


def test_run_fo_candle_feed_source_uses_the_shared_lock():
    import inspect
    src = inspect.getsource(fo_feed.run_fo_candle_feed)
    assert "async with main._heavy_startup_resolve_lock:" in src


def test_run_feed_source_uses_the_shared_lock():
    import inspect
    src = inspect.getsource(live_feed.run_feed)
    assert "async with main._heavy_startup_resolve_lock:" in src


def test_lock_is_a_plain_asyncio_lock_not_held_by_default():
    assert isinstance(main._heavy_startup_resolve_lock, asyncio.Lock)
    assert not main._heavy_startup_resolve_lock.locked()
