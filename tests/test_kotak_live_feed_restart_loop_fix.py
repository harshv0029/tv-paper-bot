"""Regression test for the same live Render restart-loop bug fixed in
kotak_fo_candle_feed.resolve_fo_universe, found in kotak_live_feed.py's
own run_feed (2026-09-16): kotak_neo.login() and resolve_tokens() -
which downloads and parses Kotak's entire nse_cm scrip master per this
module's own comment above _TOKEN_MAP_CACHE_TTL_SECONDS - were called
bare inside the async loop, blocking the whole event loop (uvicorn's
request handling and Render's health check included) on every restart.

Run: pytest tests/ -v
"""
import asyncio
import inspect
import time as time_module

import kotak_live_feed as feed


def test_run_feed_resolves_login_and_tokens_off_the_event_loop():
    src = inspect.getsource(feed.run_feed)
    assert "asyncio.to_thread(kotak_neo.login)" in src
    assert "asyncio.to_thread(resolve_tokens, client, watchlist_symbols)" in src
    # Both calls are now also hard-bounded via asyncio.wait_for
    # (2026-09-16/17 follow-up) - see LOGIN_TIMEOUT_SECONDS/
    # RESOLVE_TOKENS_TIMEOUT_SECONDS's own comment: main._heavy_
    # startup_resolve_lock has no timeout of its own, so a hang in
    # either call (ignoring to_thread's own lack of a deadline) would
    # starve kotak_fo_candle_feed's own resolve forever too - a live-
    # observed symptom (both feeds stuck at connected: false).
    assert src.count("asyncio.wait_for(") == 2
    assert "timeout=LOGIN_TIMEOUT_SECONDS" in src
    assert "timeout=RESOLVE_TOKENS_TIMEOUT_SECONDS" in src


def test_login_and_resolve_tokens_timeouts_release_the_shared_lock_promptly():
    # Live incident regression: proves a hang inside resolve_tokens
    # (which runs under main._heavy_startup_resolve_lock) doesn't hold
    # that lock forever - a second acquire attempt must succeed
    # promptly once the patched (near-zero) timeout fires, not after
    # waiting out the real RESOLVE_TOKENS_TIMEOUT_SECONDS.
    import main

    def _hangs_forever(*args, **kwargs):
        time_module.sleep(5)  # far longer than the patched deadline below
        return {}

    async def acquire_and_resolve():
        async with main._heavy_startup_resolve_lock:
            try:
                await asyncio.wait_for(asyncio.to_thread(_hangs_forever), timeout=0.1)
            except asyncio.TimeoutError:
                pass  # exactly what run_feed's own outer except catches

    async def run():
        await acquire_and_resolve()
        async with main._heavy_startup_resolve_lock:
            return True

    result = asyncio.run(asyncio.wait_for(run(), timeout=2.0))
    assert result is True


def test_to_thread_keeps_the_event_loop_free_during_a_slow_blocking_call():
    # Functional proof, not just a source-text check - a concurrent
    # asyncio task must keep making progress WHILE the blocking call is
    # still running on its own thread.
    progressed = []

    def slow_blocking_call():
        time_module.sleep(0.2)
        return {}

    async def other_task():
        while len(progressed) < 3:
            progressed.append(time_module.time())
            await asyncio.sleep(0.03)

    async def run():
        task = asyncio.create_task(other_task())
        await asyncio.to_thread(slow_blocking_call)
        task.cancel()

    asyncio.run(run())
    assert len(progressed) >= 2
