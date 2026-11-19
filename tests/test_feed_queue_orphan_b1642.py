"""B-1642: per-queue tick stats and orphaned-queue shrink in kotak_live_feed."""
import asyncio

import kotak_live_feed as klf


def test_orphaned_queue_shrinks_and_any_get_restores(monkeypatch):
    q = klf._DropOldestQueue()
    for i in range(500):
        q.put_nowait(i)
    assert q.qsize() == 500 and not q.b1642_orphaned
    q.b1642_last_get -= klf.ORPHAN_IDLE_SECONDS + 1  # nobody read it for > idle limit
    q.put_nowait("new")
    assert q.b1642_orphaned and q.qsize() == klf.ORPHAN_CAP
    assert q.get_nowait() is not None and not q.b1642_orphaned  # a consumer read clears it
    for i in range(200):
        q.put_nowait(i)
    assert q.qsize() > klf.ORPHAN_CAP


def test_async_get_counts_as_consumer():
    async def run():
        q = klf._DropOldestQueue()
        q.put_nowait(1)
        q.b1642_orphaned = True
        assert await q.get() == 1
        return q
    q = asyncio.run(run())
    assert q.b1642_consumed == 1 and not q.b1642_orphaned


def test_per_queue_stats_rows():
    q = klf._DropOldestQueue()
    q.put_nowait(1)
    rows = [r for r in klf.per_queue_stats() if r["size"] == 1 and r["consumed"] == 0]
    assert rows and set(rows[0]) == {"size", "dropped", "consumed", "idle_s", "age_s", "orphaned"}
    del q


def test_live_consumer_never_marked_orphan():
    q = klf._DropOldestQueue()
    for i in range(1000):
        q.put_nowait(i)
        q.get_nowait()
    assert not q.b1642_orphaned and q.b1642_consumed == 1000 and q.b1642_dropped == 0
