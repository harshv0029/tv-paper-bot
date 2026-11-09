"""B-1464: no test may leave a background thread running that acts on a later test's DB or patches."""
import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import main


def test_start_scheduler_in_tests_starts_no_process_lifetime_threads():
    names = ("unprotected-backcheck", "git-tier-push", "open-protect", "watchdog")
    before = {t.ident for t in threading.enumerate() if t.name in names}
    noop = MagicMock(return_value=None)
    patches = [patch(f"main.{n}", MagicMock(return_value=v)) for n, v in (
        ("hydrate_runtime_settings_from_external", 0), ("hydrate_t1_restricted_from_external", 0),
        ("hydrate_real_positions_from_external", True), ("hydrate_rr_cursor_from_external", None),
        ("hydrate_check_counts_from_external", None))]
    patches += [patch(f"main.{n}", noop) for n in (
        "reconcile_open_positions_from_journal", "reconcile_trading_control_from_journal",
        "reconcile_real_trading_control_from_journal", "reconcile_real_positions_from_journal",
        "reconcile_real_trades_today_from_journal", "reconcile_scheduler_check_counts_from_journal")]
    patches += [patch("main.get_db", return_value=MagicMock()), patch("main._scheduler_loop", noop),
                patch("kotak_live_feed.run_feed", noop), patch("kotak_fo_candle_feed.run_fo_candle_feed", noop),
                patch("asyncio.create_task", MagicMock())]
    for p in patches:
        p.start()
    try:
        asyncio.run(main._start_scheduler())
    finally:
        for p in patches:
            p.stop()
    after = {t.ident for t in threading.enumerate() if t.name in names}
    assert after == before  # nothing new: the conftest guard holds, so no loop can fire inside a later test


def test_chan_gap_selection_thread_does_not_fetch_the_universe_in_tests():
    main._CHAN_GAP_STATE.update(day=None, ready=False, building=False, selected={})
    try:
        assert main._chan_gap_ensure_selection("2099-03-03", ["IREDA.NS", "TCS.NS"]) is False
        deadline = time.time() + 5
        while not main._CHAN_GAP_STATE["ready"] and time.time() < deadline:
            time.sleep(0.01)
        assert main._CHAN_GAP_STATE["ready"] and main._CHAN_GAP_STATE["selected"] == {}  # stub: no fetch, done at once
    finally:
        main._CHAN_GAP_STATE.update(day=None, ready=False, building=False, selected={})
