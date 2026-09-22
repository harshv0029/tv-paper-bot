"""Tests for the swing (Gap and Go) scan counter (2026-09-22, explicit
user request: a counter + distinct-tracked-assets line for the swing
engine on /trade-view, mirroring the intraday banner but reported
separately - see the module comment above _swing_check_counts in main.py
for why it's not folded into _scheduler_check_counts."""
from unittest.mock import patch

import main


def _reset():
    main._swing_check_counts.clear()
    main._swing_check_counts_day = ""


def test_record_swing_check_counts_per_symbol():
    _reset()
    main._record_swing_check("RELIANCE.NS")
    main._record_swing_check("RELIANCE.NS")
    main._record_swing_check("TCS.NS")
    assert main._swing_check_counts["RELIANCE.NS"] == 2
    assert main._swing_check_counts["TCS.NS"] == 1


def test_record_swing_check_resets_on_day_rollover():
    _reset()
    with patch("main.ist_now") as mock_now:
        mock_now.return_value.strftime.return_value = "2026-09-21"
        main._record_swing_check("RELIANCE.NS")
        assert main._swing_check_counts["RELIANCE.NS"] == 1

        mock_now.return_value.strftime.return_value = "2026-09-22"
        main._record_swing_check("TCS.NS")
        assert "RELIANCE.NS" not in main._swing_check_counts
        assert main._swing_check_counts["TCS.NS"] == 1


def test_swing_check_counts_independent_of_intraday_counts():
    _reset()
    main._scheduler_check_counts.clear()
    main._record_swing_check("RELIANCE.NS")
    main._record_scheduler_check("RELIANCE.NS")
    # Same symbol, two completely separate counters - one entry each,
    # neither blended into the other.
    assert main._swing_check_counts["RELIANCE.NS"] == 1
    assert main._scheduler_check_counts["RELIANCE.NS"] == 1


def test_scheduler_pipeline_exposes_swing_scan_counters():
    _reset()
    for sym in main.SWING_WATCHLIST[:3]:
        main._record_swing_check(sym)
    main._record_swing_check(main.SWING_WATCHLIST[0])  # scanned twice
    pipeline = main.scheduler_pipeline()
    assert pipeline["swing_scanned_today_total"] == len(main.SWING_WATCHLIST)
    assert pipeline["swing_scanned_today_count"] == 3
    assert pipeline["swing_total_checks_today"] == 4
