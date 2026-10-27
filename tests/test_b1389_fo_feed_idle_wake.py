"""B-1389: the F&O stream loop wakes on a silent stream so a finished background resolve is swapped in
(live 2026-10-27: resolve finished 18:45 IST after the close, no ticks, swap never happened)."""
import asyncio
import inspect

import kotak_fo_candle_feed as feed


def test_loop_waits_with_idle_timeout_and_checks_bg_resolve_before_ticks():
    src = inspect.getsource(feed.run_fo_candle_feed)
    loop = src.split("ticks = ws.__aiter__()")[1]
    assert "asyncio.wait_for(ticks.__anext__(), timeout=STREAM_IDLE_WAKE_SECONDS)" in loop
    assert loop.index("background_resolve_step(main)") < loop.index("process_fo_ticks(")
    assert "except StopAsyncIteration" in loop
    assert 0 < feed.STREAM_IDLE_WAKE_SECONDS <= 10


class _QueueWs:
    """Same __anext__ shape as neo_api_client's feed client: an inner 1 s queue.get loop."""
    def __init__(self):
        self.q = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            try:
                return await asyncio.wait_for(self.q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                pass


def test_timed_out_wait_drops_no_message():
    async def run():
        ws = _QueueWs()
        it = ws.__aiter__()
        try:
            await asyncio.wait_for(it.__anext__(), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        ws.q.put_nowait("tick")
        return await asyncio.wait_for(it.__anext__(), timeout=2)
    assert asyncio.run(run()) == "tick"
