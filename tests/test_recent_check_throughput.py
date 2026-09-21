"""Tests for the rolling-window scan-throughput signal (2026-09-21,
explicit user instruction: "I want an additional line mentioning that
'x is total scanned ones in last 30 seconds'" - the daily distinct-
scanned count necessarily plateaus once the whole (now 206-symbol,
NIFTY 200) WATCHLIST has been covered at least once today, which reads
as "stalled" even while the scheduler keeps actively re-scanning it.
This is the separate signal that actually shows live throughput)."""
from unittest.mock import patch

import main


def _reset():
    main._recent_check_timestamps.clear()
    main._scheduler_check_counts.clear()
    main._scheduler_check_counts_day = ""


def test_checks_in_last_seconds_counts_only_recent_entries():
    _reset()
    now = 1_000_000.0
    with patch("main.time.time", return_value=now - 100):
        main._record_scheduler_check("OLD.NS")
    with patch("main.time.time", return_value=now - 10):
        main._record_scheduler_check("RECENT.NS")
    with patch("main.time.time", return_value=now):
        assert main.checks_in_last_seconds(30) == 1


def test_checks_in_last_seconds_counts_multiple_checks_in_window():
    _reset()
    now = 1_000_000.0
    for offset in (25, 15, 5, 1):
        with patch("main.time.time", return_value=now - offset):
            main._record_scheduler_check(f"SYM{offset}.NS")
    with patch("main.time.time", return_value=now):
        assert main.checks_in_last_seconds(30) == 4


def test_checks_in_last_seconds_zero_when_nothing_recent():
    _reset()
    now = 1_000_000.0
    with patch("main.time.time", return_value=now - 500):
        main._record_scheduler_check("STALE.NS")
    with patch("main.time.time", return_value=now):
        assert main.checks_in_last_seconds(30) == 0


def test_record_scheduler_check_prunes_stale_timestamps():
    _reset()
    now = 1_000_000.0
    with patch("main.time.time", return_value=now - 500):
        main._record_scheduler_check("VERY_OLD.NS")
    assert len(main._recent_check_timestamps) == 1
    with patch("main.time.time", return_value=now):
        main._record_scheduler_check("FRESH.NS")
        # the 500s-old entry is well past _RECENT_CHECK_RETENTION_SECONDS
        # (120) and must be pruned by the newer call, not accumulate forever.
        assert len(main._recent_check_timestamps) == 1
        assert main.checks_in_last_seconds(30) == 1


def test_scheduler_pipeline_and_scheduler_status_expose_checks_last_30s():
    _reset()
    now = 1_000_000.0
    with patch("main.time.time", return_value=now):
        main._record_scheduler_check("LIVE.NS")
        pipeline = main.scheduler_pipeline()
        status = main.scheduler_status()
    assert pipeline["checks_last_30s"] == 1
    assert status["checks_last_30s"] == 1
