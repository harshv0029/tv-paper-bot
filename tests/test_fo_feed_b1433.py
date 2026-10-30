"""B-1433: a full F&O resolve that runs out of its 600 s deadline (live 30-Oct: 74 of 210 stocks, ~136
"deadline_exceeded") must keep resolving in background rounds until every stock has been attempted, instead of
waiting for the next 4h refresh - while legs already resolved stay in the universe."""
import asyncio
import time
import types

import pytest

import kotak_fo_candle_feed as feed

STOCKS = tuple(f"S{i:03d}" for i in range(10))
PER_ROUND = 4


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(feed.nse_fo_chain, "STOCK_FO_UNDERLYINGS", STOCKS)
    monkeypatch.setattr(feed, "_stock_resolve_offset", {"value": 0})
    monkeypatch.setattr(feed, "_universe_cache", {"value": {("i", "0"): {"underlying": "NIFTY"}},
                                                   "resolved_at": time.time(), "partial": True})
    monkeypatch.setattr(feed, "_bg_resolve", {"task": None, "failed_at": 0.0, "swapped": False})
    monkeypatch.setattr(feed, "_feed_status", dict(feed._feed_status))
    monkeypatch.setattr(feed, "universe_refresh_due", lambda *a, **k: False)
    monkeypatch.setattr(feed, "CONTINUATION_GAP_SECONDS", 0, raising=False)
    monkeypatch.setattr(feed, "_resolve_continuation",
                        {"due": False, "attempted": 0, "rounds": 0, "last_done_at": 0.0}, raising=False)
    calls = []

    def fake_resolve(deadline=None, stock_offset=0, previous_universe=None, index_only=False):
        # resolves PER_ROUND stocks from the offset, the rest hit the deadline (carried forward like the real one)
        calls.append(stock_offset)
        uni, unresolved, exceeded = {("i", "0"): {"underlying": "NIFTY"}}, [], set()
        for i in range(len(STOCKS)):
            name = STOCKS[(stock_offset + i) % len(STOCKS)]
            if i < PER_ROUND:
                uni[("s", name)] = {"underlying": name}
            else:
                unresolved.append(f"{name}:deadline_exceeded")
                exceeded.add(name)
        for k, d in (previous_universe or {}).items():
            if d["underlying"] in exceeded and k not in uni:
                uni[k] = d
        feed._feed_status["unresolved_legs"] = unresolved
        return uni
    monkeypatch.setattr(feed, "resolve_fo_universe", fake_resolve)
    return calls


def test_background_resolve_continues_until_every_stock_attempted(setup):
    calls = setup
    main_mod = types.SimpleNamespace(_heavy_startup_resolve_lock=asyncio.Lock())

    async def run():
        swaps = 0
        for _ in range(2000):
            if feed.background_resolve_step(main_mod):
                swaps += 1
                feed._universe_cache["partial"] = False  # as after the real swap
            await asyncio.sleep(0.005)
            if feed._bg_resolve["task"] is None and not feed._universe_cache["partial"] \
                    and not feed._resolve_continuation["due"]:
                break
        return swaps
    swaps = asyncio.run(run())
    stocks_in_universe = {d["underlying"] for d in feed._universe_cache["value"].values()} - {"NIFTY"}
    # old code: one background resolve (4 of 10 stocks), then nothing until the 4h refresh
    assert stocks_in_universe == set(STOCKS)
    assert calls == [0, 4, 8]  # rotated offset, ceil(10/4) rounds, then stops
    assert swaps == 3
    assert feed._resolve_continuation["due"] is False
    assert feed._feed_status["resolve_continuation"]["stocks_attempted_this_cycle"] == len(STOCKS)


def test_continuation_waits_for_gap(setup, monkeypatch):
    monkeypatch.setattr(feed, "CONTINUATION_GAP_SECONDS", 30)
    feed._universe_cache["partial"] = False
    feed._resolve_continuation.update(due=True, attempted=4, last_done_at=time.time())
    assert feed.background_resolve_step(None) is False and feed._bg_resolve["task"] is None

    async def run():
        assert feed.background_resolve_step(None, now=time.time() + 31) is False
        task = feed._bg_resolve["task"]
        assert task is not None
        task.cancel()
    asyncio.run(run())
