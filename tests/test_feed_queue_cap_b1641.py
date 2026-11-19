"""B-1641: the SDK tick queue is capped drop-oldest, so a lagging event loop can no longer OOM Render."""
import asyncio

import kotak_live_feed as klf


class _WS:
    def __init__(self):
        self._message_queue = asyncio.Queue()


def test_cap_drops_oldest_and_never_raises(monkeypatch):
    monkeypatch.setattr(klf, "QUEUE_SOFT_CAP", 5)
    ws = _WS()
    ws._message_queue.put_nowait("pre")
    klf.cap_ws_queue(ws)
    assert isinstance(ws._message_queue, klf._DropOldestQueue) and ws._message_queue.qsize() == 1
    before = klf.queue_stats["dropped"]
    for i in range(12):
        ws._message_queue.put_nowait(i)
    assert ws._message_queue.qsize() == 5
    assert [ws._message_queue.get_nowait() for _ in range(5)] == [7, 8, 9, 10, 11]  # newest kept
    assert klf.queue_stats["dropped"] - before == 8


def test_drain_pending_works_on_capped_queue():
    ws = _WS()
    klf.cap_ws_queue(ws)
    for i in range(3):
        ws._message_queue.put_nowait(i)
    assert klf.drain_pending(ws, "first") == ["first", 0, 1, 2]


def test_cap_is_idempotent_and_safe_without_queue():
    ws = _WS()
    klf.cap_ws_queue(ws)
    q = ws._message_queue
    klf.cap_ws_queue(ws)
    assert ws._message_queue is q
    klf.cap_ws_queue(object())  # no attribute: no error


def test_real_sdk_client_queue_gets_capped():
    from neo_api_client.websocket.feed import client as fc
    cls = next(v for v in vars(fc).values() if isinstance(v, type) and "_deliver_message" in vars(v))
    obj = cls.__new__(cls)
    obj._message_queue = asyncio.Queue()
    klf.cap_ws_queue(obj)
    assert isinstance(obj._message_queue, klf._DropOldestQueue)
