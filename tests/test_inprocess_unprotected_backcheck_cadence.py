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


def test_backcheck_cadence_constant_is_a_sane_positive_tick_count():
    assert isinstance(main._UNPROTECTED_BACKCHECK_EVERY_N_TICKS, int)
    assert main._UNPROTECTED_BACKCHECK_EVERY_N_TICKS > 0
    # ~5 minutes at the documented 30s tick interval - the exact cadence
    # the MFSL.NS rule requires, not a slower one.
    minutes = (main._UNPROTECTED_BACKCHECK_EVERY_N_TICKS * main.SCHEDULER_INTERVAL_SECONDS) / 60
    assert minutes <= 5.5


def test_scheduler_tick_source_calls_reconcile_gated_by_the_cadence_constant():
    src = inspect.getsource(main._scheduler_tick)
    assert "_UNPROTECTED_BACKCHECK_EVERY_N_TICKS" in src
    assert '_reconcile_real_positions_core(adopt="*")' in src


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


def test_tick_runs_the_backcheck_on_the_cadence_boundary():
    _fresh_db()
    reconcile_mock = MagicMock(return_value={"unprotected_positions_count": 0})
    original_count = main._scheduler_tick_count
    try:
        main._scheduler_tick_count = main._UNPROTECTED_BACKCHECK_EVERY_N_TICKS - 1
        _run_tick_with_heavy_mocks(reconcile_mock)
    finally:
        main._scheduler_tick_count = original_count
    reconcile_mock.assert_called_once_with(adopt="*")


def test_tick_skips_the_backcheck_off_the_cadence_boundary():
    _fresh_db()
    reconcile_mock = MagicMock(return_value={"unprotected_positions_count": 0})
    original_count = main._scheduler_tick_count
    try:
        main._scheduler_tick_count = 1  # + 1 = 2, not a multiple of the cadence
        _run_tick_with_heavy_mocks(reconcile_mock)
    finally:
        main._scheduler_tick_count = original_count
    reconcile_mock.assert_not_called()


def test_a_reconcile_failure_on_the_backcheck_tick_never_crashes_the_tick():
    # Isolation, same principle as every other block in this loop - a
    # Kotak/network hiccup during the backcheck must never block the rest
    # of the scan (entries/exits/real order sync for every other symbol).
    _fresh_db()
    reconcile_mock = MagicMock(side_effect=Exception("kotak_neo timeout"))
    original_count = main._scheduler_tick_count
    try:
        main._scheduler_tick_count = main._UNPROTECTED_BACKCHECK_EVERY_N_TICKS - 1
        _run_tick_with_heavy_mocks(reconcile_mock)  # must not raise
    finally:
        main._scheduler_tick_count = original_count
    reconcile_mock.assert_called_once_with(adopt="*")
