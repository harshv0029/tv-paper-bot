"""B-1388: cold start subscribes index legs first; the full resolve runs in the background while streaming."""
import asyncio
import time

import kotak_fo_candle_feed as feed


def test_index_only_skips_stocks(monkeypatch):
    calls = []
    monkeypatch.setattr(feed, "_spot_price", lambda sym: calls.append(sym) or 100.0)
    monkeypatch.setattr(feed, "_resolve_underlying_legs",
                        lambda name, spot, band, classes, uni, unres: uni.__setitem__(("seg", name), {"underlying": name}))
    uni = feed.resolve_fo_universe(index_only=True)
    assert set(calls) == set(feed.FO_CANDLE_UNDERLYINGS.keys())
    assert {d["underlying"] for d in uni.values()} == set(feed.INDEX_UNDERLYING_NAMES)
    assert "stocks:deferred_to_background_resolve" in feed._feed_status["unresolved_legs"]


def test_background_step_starts_once_and_reports_swap(monkeypatch):
    async def run():
        done = asyncio.Event()

        async def fake_full(main_mod):
            feed._universe_cache.update(value={("s", "1"): {}}, resolved_at=time.time(), partial=False)
            done.set()
            return feed._universe_cache["value"]
        monkeypatch.setattr(feed, "_resolve_full_universe", fake_full)
        feed._bg_resolve.update(task=None, failed_at=0.0, swapped=False)
        feed._universe_cache.update(value={("s", "0"): {}}, resolved_at=time.time(), partial=True)
        assert feed.background_resolve_step(None) is False
        first = feed._bg_resolve["task"]
        assert first is not None
        assert feed.background_resolve_step(None) is False and feed._bg_resolve["task"] is first  # not respawned
        await done.wait()
        await asyncio.sleep(0)
        assert feed.background_resolve_step(None) is True  # swap ready -> reconnect
        assert feed._bg_resolve["task"] is None and feed._universe_cache["partial"] is False
        monkeypatch.setattr(feed, "universe_refresh_due", lambda: False)
        assert feed.background_resolve_step(None) is False and feed._bg_resolve["task"] is None
    asyncio.run(run())


def test_failed_background_resolve_backs_off(monkeypatch):
    async def run():
        async def boom(main_mod):
            raise RuntimeError("kotak down")
        monkeypatch.setattr(feed, "_resolve_full_universe", boom)
        feed._bg_resolve.update(task=None, failed_at=0.0, swapped=False)
        feed._universe_cache.update(value={("s", "0"): {}}, resolved_at=time.time(), partial=True)
        feed.background_resolve_step(None)
        await asyncio.sleep(0.01)
        assert feed.background_resolve_step(None) is False  # collects the failed task
        assert feed.background_resolve_step(None) is False and feed._bg_resolve["task"] is None  # within backoff
        assert feed.background_resolve_step(None, now=time.time() + feed.BG_RESOLVE_RETRY_SECONDS + 1) is False
        assert feed._bg_resolve["task"] is not None  # retried after backoff
        await asyncio.sleep(0.01)
        feed.background_resolve_step(None)
    asyncio.run(run())
    feed._bg_resolve.update(task=None, failed_at=0.0, swapped=False)
    feed._universe_cache.update(value=None, resolved_at=0.0, partial=False)
