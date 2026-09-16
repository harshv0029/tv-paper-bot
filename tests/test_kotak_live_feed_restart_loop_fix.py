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
    assert "await asyncio.to_thread(kotak_neo.login)" in src
    assert "await asyncio.to_thread(resolve_tokens, client, watchlist_symbols)" in src


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
