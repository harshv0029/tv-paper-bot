"""B-1432: residual Render RSS growth after B-1431 (live 30-Oct 10:57 -> 11:50 IST: SFeedScrip 0 -> 7.9k,
DepthLevel 15.8k, set +23.6k = 3 pydantic models per tick, list +16k = buy/sell lists per tick) - Kotak feed ticks
retained in the SDK's unbounded queue because nothing was consuming it.

1. The F&O candle feed processed each tick batch via asyncio.to_thread, i.e. queued behind every other job on the
   loop's shared default executor (scans, prefetch); while that pool is busy the consumer is parked and the SDK
   queue grows. It now uses its own single-worker executor.
2. A consumer leaving its stream disables the SDK client's own auto-reconnect before close, so a reconnect that
   races close() cannot leave an orphan client streaming into a queue nobody reads."""
import asyncio
import concurrent.futures
import threading

import kotak_fo_candle_feed as fo
import kotak_live_feed as lf
from neo_api_client.websocket.feed import DepthLevel, SFeedScrip, SFeedWebSocket


def _tick(tok, ltp):
    return SFeedScrip.model_construct(
        exchange_segment="nse_fo", instrument_token=str(tok), last_traded_price=ltp, level=4,
        buy=[DepthLevel.model_construct(quantity=1, price=ltp, orders=1)],
        sell=[DepthLevel.model_construct(quantity=1, price=ltp, orders=1)])


class _FakeWs:
    """Same consumer-facing shape as SFeedWebSocket: async CM, subscribe_scrips, __anext__ = 1 s queue.get loop."""

    def __init__(self):
        self._message_queue = asyncio.Queue()
        self.max_reconnect_attempts = 5
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        self.closed = True

    async def subscribe_scrips(self, tokens):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            try:
                return await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                pass


class _FakeClient:
    def __init__(self, ws):
        self.ws = ws

    def create_websocket(self):
        return self.ws


def test_fo_ticks_consumed_while_default_executor_is_busy(monkeypatch):
    """Old code: the batch waits behind a busy default executor and the queue only grows."""
    ws = _FakeWs()
    universe = {("nse_fo", str(t)): {"kotak_trading_symbol": f"OPT{t}", "underlying": "NIFTY"} for t in range(1, 51)}
    monkeypatch.setattr(fo.kotak_neo, "login", lambda: _FakeClient(ws))
    monkeypatch.setattr(fo, "_universe_cache", {"value": universe, "resolved_at": 9e18, "partial": False})
    monkeypatch.setattr(fo, "_bg_resolve", {"task": None, "failed_at": 0.0, "swapped": False})
    monkeypatch.setattr(fo, "background_resolve_step", lambda main_mod, now=None: False)
    monkeypatch.setattr(fo, "universe_refresh_due", lambda *a, **k: False)
    monkeypatch.setattr(fo, "_in_progress_candles", {})
    monkeypatch.setattr(fo, "_feed_status", dict(fo._feed_status, ticks_received=0))

    release = threading.Event()

    async def run():
        loop = asyncio.get_running_loop()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(pool)
        blocker = loop.run_in_executor(None, release.wait, 30)  # e.g. a long swing scan on the shared pool
        task = asyncio.create_task(fo.run_fo_candle_feed())
        try:
            for rnd in range(5):
                for t in range(1, 51):
                    ws._message_queue.put_nowait(_tick(t, 100.0 + rnd))
                await asyncio.sleep(0.3)
            return fo._feed_status["ticks_received"], ws._message_queue.qsize()
        finally:
            release.set()
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            await blocker
            pool.shutdown(wait=False)

    received, backlog = asyncio.run(run())
    assert received == 250, f"only {received} of 250 ticks consumed while the default executor was busy"
    assert backlog == 0
    bar = fo._in_progress_candles["7"]
    assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["tick_count"]) == (100.0, 104.0, 100.0, 104.0, 5)


def test_fo_tick_executor_is_dedicated_single_worker():
    assert fo._FO_TICK_EXECUTOR._max_workers == 1


def test_retiring_disables_sdk_reconnect_before_close_and_clears_queue():
    seen = {}

    class _Ws(_FakeWs):
        async def __aexit__(self, *a):
            seen["attempts_at_close"] = self.max_reconnect_attempts
            self.closed = True

    async def run():
        ws = _Ws()
        async with lf.retiring(ws) as got:
            assert got is ws
            got._message_queue.put_nowait(_tick(1, 1.0))
        return ws

    ws = asyncio.run(run())
    assert seen["attempts_at_close"] == 0 and ws.closed and ws._message_queue.qsize() == 0


def test_retired_sdk_client_does_not_reconnect_itself():
    """The real SDK: after retire_ws, _handle_disconnect (the receive task's reconnect path) never calls connect()."""
    async def run():
        ws = SFeedWebSocket(access_token="t", sid="s", reconnect_delay=0)
        calls = []

        async def fake_connect():
            calls.append(1)
        ws.connect = fake_connect
        lf.retire_ws(ws)
        await ws._handle_disconnect()
        return calls

    assert asyncio.run(run()) == []


def test_both_feeds_use_retiring():
    import inspect
    assert "retiring(client.create_websocket())" in inspect.getsource(lf.run_feed)
    assert "retiring(client.create_websocket())" in inspect.getsource(fo.run_fo_candle_feed)
