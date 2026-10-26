import datetime
"""Tests for the 2026-09-30 in-process unprotected-position backcheck
(second live incident of the MFSL.NS pattern: TCS.NS and INDIANB.NS both
sat with NO live resting stop-loss at Kotak for a real stretch of market
time, found by the user directly on the Kotak app - the dashboard's own
/real-protection-status looked stale because it does).

Root cause: the 2026-09-30 MFSL.NS CLAUDE.md rule's "every 5 min" backcheck
guarantee lived entirely in kotak-reconcile.yml's external GitHub Actions
cron (`*/5 3-10 * * 1-5`). Checking actions_list for that workflow's own
`event: schedule` runs showed real gaps of 5-8+ hours between fires on
2026-09-28/29/30 - GitHub's own scheduler was not honoring the configured
cadence for this repo, likely due to the very high volume of OTHER
workflow_dispatch runs this repo generates. The external cron stays as a
secondary check + durable audit log, but _scheduler_tick (the in-process
~30s loop, proven reliable all session - it's what already runs
_maybe_sync_real_stop_loss/_maybe_sync_real_stop_loss_short every tick)
now also calls _reconcile_real_positions_core(adopt="*") every
_UNPROTECTED_BACKCHECK_EVERY_N_TICKS ticks, so the 5-min guarantee no
longer depends on any external scheduler's reliability at all.

Run: pytest tests/test_inprocess_unprotected_backcheck_cadence.py -v
"""
import asyncio
import inspect
import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_backcheck_runs_on_its_own_5_min_wall_clock_thread():
    """B-1354: the backcheck no longer rides the scan tick (one tick can take minutes); its own loop sleeps 300 s."""
    assert main._UNPROTECTED_BACKCHECK_EVERY_SECONDS <= 300
    reconcile_mock = MagicMock(return_value={"unprotected_positions_count": 0})
    sleeps = []
    real_next = main._unprotected_backcheck_next_sleep
    eleven_am = datetime.datetime(2026, 10, 27, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    # B-1363: fixed mid-session clock; inside 09:15-09:30 IST the loop deliberately runs every 20 s instead.
    with patch("main._reconcile_real_positions_core", reconcile_mock), \
            patch("main._unprotected_backcheck_next_sleep", lambda: real_next(eleven_am)):
        main._unprotected_backcheck_loop(sleep=sleeps.append, rounds=3)
    assert reconcile_mock.call_count == 3 and sleeps == [300] * 3
    reconcile_mock.assert_called_with(adopt="*")


def test_backcheck_thread_is_started_at_startup():
    assert "_unprotected_backcheck_loop" in inspect.getsource(main)
    src = inspect.getsource(main._scheduler_tick)
    assert "% _UNPROTECTED_BACKCHECK_EVERY_N_TICKS" not in src  # no tick-count dependency any more
    assert "asyncio.to_thread(_unprotected_backcheck_once)" in src  # 09:15-09:30 pass, off the event loop


def test_backcheck_is_single_flight():
    assert main._unprotected_backcheck_lock.acquire(blocking=False)
    try:
        with patch("main._reconcile_real_positions_core") as rc:
            assert main._unprotected_backcheck_once() is False
            rc.assert_not_called()
    finally:
        main._unprotected_backcheck_lock.release()


def test_a_reconcile_failure_never_kills_the_backcheck_loop():
    reconcile_mock = MagicMock(side_effect=Exception("kotak_neo timeout"))
    with patch("main._reconcile_real_positions_core", reconcile_mock):
        main._unprotected_backcheck_loop(sleep=lambda s: None, rounds=2)  # must not raise
    assert reconcile_mock.call_count == 2


_FIXTURE = pd.DataFrame([
    {"Date": pd.Timestamp("2026-09-30 03:45:00") + pd.Timedelta(minutes=5 * i),
     "Open": 100.0, "High": 100.5, "Low": 99.5, "Close": 100.0, "Volume": 1000}
    for i in range(30)
])


def _run_tick_with_heavy_mocks(reconcile_mock):
    with patch("main._run_swing_scan"), \
         patch("main._fo_chain_monitoring_snapshot"), \
         patch("main._run_fo_options_scan"), \
         patch("main.fetch_ohlc", return_value=_FIXTURE), \
         patch("main.get_scheduler_capital_inr", return_value=400000.0), \
         patch("kotak_live_feed.get_live_ticks", return_value={}), \
         patch("main._maybe_sync_real_stop_loss"), \
         patch("main._maybe_place_real_entry"), \
         patch("main._maybe_place_real_exit"), \
         patch("main._maybe_place_real_partial_exit"), \
         patch("main._maybe_sync_real_stop_loss_short"), \
         patch("main._maybe_place_real_short_entry"), \
         patch("main._maybe_place_real_short_exit"), \
         patch("main._reconcile_real_positions_core", reconcile_mock):
        asyncio.run(main._scheduler_tick())


def test_tick_outside_the_open_window_does_not_run_the_backcheck():
    _fresh_db()
    reconcile_mock = MagicMock(return_value={"unprotected_positions_count": 0})
    original_count = main._scheduler_tick_count
    try:
        main._scheduler_tick_count = 1  # + 1 = 2, not a multiple of the cadence
        # Fixed 11:00 IST weekday: at a real 09:15-09:30 IST run time the tick's open-window pass would fire.
        with patch("main.ist_now", return_value=datetime.datetime(2026, 10, 27, 11, 0)):
            _run_tick_with_heavy_mocks(reconcile_mock)
    finally:
        main._scheduler_tick_count = original_count
    reconcile_mock.assert_not_called()
