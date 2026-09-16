"""Regression tests for _start_scheduler's Upstash-hydration fix
(2026-09-16, live Render port-scan-timeout incident): the 5 startup
hydrate_*_from_external calls used to run sequentially, summing their
worst-case latency to up to ~50s - long enough, confirmed live, to
block Render's port scanner from ever seeing an open port (FastAPI/
uvicorn's lifespan protocol gates the actual listening socket behind
this startup handler returning). Fixed to run them concurrently via
asyncio.gather/asyncio.to_thread. These tests confirm (a) the wall-time
win is real, not just a source-text change, and (b) every downstream
ordering/fallback decision that depended on each call's result still
behaves identically.

Run: pytest tests/ -v
"""
import asyncio
import time as time_module
from unittest.mock import MagicMock, patch

import main


def _patched_start_scheduler(**overrides):
    defaults = {
        "hydrate_runtime_settings_from_external": MagicMock(return_value=0),
        "hydrate_t1_restricted_from_external": MagicMock(return_value=0),
        "hydrate_real_positions_from_external": MagicMock(return_value=True),
        "hydrate_rr_cursor_from_external": MagicMock(return_value=None),
        "hydrate_check_counts_from_external": MagicMock(return_value=None),
        "reconcile_open_positions_from_journal": MagicMock(),
        "reconcile_trading_control_from_journal": MagicMock(),
        "reconcile_real_trading_control_from_journal": MagicMock(),
        "reconcile_real_positions_from_journal": MagicMock(),
        "reconcile_real_trades_today_from_journal": MagicMock(),
        "reconcile_scheduler_check_counts_from_journal": MagicMock(),
    }
    defaults.update(overrides)
    patches = [patch(f"main.{name}", fn) for name, fn in defaults.items()]
    # get_db() is called inside the runtime_settings/t1 closures, each
    # on its own worker thread - contextlib.closing() only needs a
    # .close() method on whatever it wraps, which a plain MagicMock
    # already provides, so this never touches a real sqlite file.
    patches.append(patch("main.get_db", return_value=MagicMock()))
    # Plain (non-coroutine) mocks, not just a mocked create_task - a
    # coroutine object created but never awaited (which patching only
    # asyncio.create_task would leave behind) triggers Python's own
    # "coroutine was never awaited" warning noise.
    patches.append(patch("main._scheduler_loop", MagicMock(return_value=None)))
    patches.append(patch("kotak_live_feed.run_feed", MagicMock(return_value=None)))
    patches.append(patch("kotak_fo_candle_feed.run_fo_candle_feed", MagicMock(return_value=None)))
    patches.append(patch("asyncio.create_task", MagicMock()))
    return patches, defaults


def test_start_scheduler_runs_hydration_concurrently_not_sequentially():
    # Each hydrate call sleeps 0.15s - sequential would take ~0.75s
    # (5x), concurrent should take close to 0.15s (the slowest single
    # call). This is the actual bug: sequential summing is what blocked
    # Render's port scanner live.
    def _slow(value):
        def _fn(*args, **kwargs):
            time_module.sleep(0.15)
            return value
        return _fn

    patches, _ = _patched_start_scheduler(
        hydrate_runtime_settings_from_external=_slow(0),
        hydrate_t1_restricted_from_external=_slow(0),
        hydrate_real_positions_from_external=_slow(True),
        hydrate_rr_cursor_from_external=_slow(None),
        hydrate_check_counts_from_external=_slow(None),
    )
    for p in patches:
        p.start()
    try:
        start = time_module.time()
        asyncio.run(main._start_scheduler())
        elapsed = time_module.time() - start
    finally:
        for p in patches:
            p.stop()
    # Well under the 0.75s a sequential run would take, comfortably
    # above the 0.15s floor a single call takes.
    assert elapsed < 0.5


def test_start_scheduler_falls_back_to_journal_when_upstash_positions_hydration_fails():
    patches, defaults = _patched_start_scheduler(hydrate_real_positions_from_external=MagicMock(return_value=False))
    for p in patches:
        p.start()
    try:
        asyncio.run(main._start_scheduler())
    finally:
        for p in patches:
            p.stop()
    defaults["reconcile_real_positions_from_journal"].assert_called_once()


def test_start_scheduler_skips_journal_fallback_when_upstash_positions_hydration_succeeds():
    patches, defaults = _patched_start_scheduler(hydrate_real_positions_from_external=MagicMock(return_value=True))
    for p in patches:
        p.start()
    try:
        asyncio.run(main._start_scheduler())
    finally:
        for p in patches:
            p.stop()
    defaults["reconcile_real_positions_from_journal"].assert_not_called()


def test_start_scheduler_restores_rr_cursor_from_upstash_when_present():
    patches, _ = _patched_start_scheduler(hydrate_rr_cursor_from_external=MagicMock(return_value=42))
    for p in patches:
        p.start()
    try:
        main._scheduler_rr_cursor = 0
        asyncio.run(main._start_scheduler())
        assert main._scheduler_rr_cursor == 42
    finally:
        for p in patches:
            p.stop()


def test_start_scheduler_leaves_rr_cursor_untouched_when_upstash_has_none():
    patches, _ = _patched_start_scheduler(hydrate_rr_cursor_from_external=MagicMock(return_value=None))
    for p in patches:
        p.start()
    try:
        main._scheduler_rr_cursor = 7
        asyncio.run(main._start_scheduler())
        assert main._scheduler_rr_cursor == 7
    finally:
        for p in patches:
            p.stop()


def test_start_scheduler_restores_check_counts_only_when_day_matches_today():
    today = main.ist_now().strftime("%Y-%m-%d")
    patches, _ = _patched_start_scheduler(
        hydrate_check_counts_from_external=MagicMock(return_value=(today, {"RELIANCE.NS": 3}))
    )
    for p in patches:
        p.start()
    try:
        main._scheduler_check_counts.clear()
        asyncio.run(main._start_scheduler())
        assert main._scheduler_check_counts.get("RELIANCE.NS") == 3
        assert main._scheduler_check_counts_day == today
    finally:
        for p in patches:
            p.stop()


def test_start_scheduler_falls_back_when_a_hydrate_call_hangs_past_the_deadline():
    # Live incident (2026-09-16): a hydrate call can hang INDEFINITELY -
    # e.g. a stalled DNS lookup or a wedged TCP connection ignores
    # requests' own timeout= entirely - which would stall the whole
    # asyncio.gather forever with no way for that per-call timeout to
    # ever fire. asyncio.wait_for's outer deadline must still let
    # _start_scheduler complete (falling back exactly as it would for
    # a clean Upstash-unreachable result) rather than hang the whole
    # app's boot forever.
    def _hangs_forever(*args, **kwargs):
        time_module.sleep(5)  # far longer than the patched deadline below
        return 999  # never actually reached within the test

    patches, defaults = _patched_start_scheduler(hydrate_rr_cursor_from_external=_hangs_forever)
    patches.append(patch("main.STARTUP_HYDRATION_TIMEOUT_SECONDS", 0.1))
    for p in patches:
        p.start()
    try:
        main._scheduler_rr_cursor = 5
        # Not asserting on wall-clock elapsed time here: asyncio.run()
        # shuts down its default thread-pool executor on exit and waits
        # for the abandoned 5s-sleeping thread to actually finish first -
        # a test-harness artifact of asyncio.run() itself, not something
        # that happens in production (uvicorn's own event loop never
        # closes after startup, so an abandoned thread just sits idle in
        # the pool rather than blocking anything). What matters here is
        # that _start_scheduler's own await returns via the fallback
        # path rather than hanging on the stuck call forever.
        asyncio.run(main._start_scheduler())
    finally:
        for p in patches:
            p.stop()
    # Left rr_cursor untouched - the exact same "nothing restored"
    # outcome a clean Upstash-unreachable result would produce.
    assert main._scheduler_rr_cursor == 5


def test_start_scheduler_ignores_check_counts_from_a_stale_prior_day():
    patches, _ = _patched_start_scheduler(
        hydrate_check_counts_from_external=MagicMock(return_value=("2020-01-01", {"RELIANCE.NS": 3}))
    )
    for p in patches:
        p.start()
    try:
        main._scheduler_check_counts.clear()
        asyncio.run(main._start_scheduler())
        assert "RELIANCE.NS" not in main._scheduler_check_counts
    finally:
        for p in patches:
            p.stop()
