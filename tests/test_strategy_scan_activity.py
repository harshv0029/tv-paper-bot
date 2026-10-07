"""Tests for GET /strategy-scan-activity (explicit user request: "viable
strategy wise count of scans done today and count of scans done in last
30 second and count of success entry using that algorithm today") - see
main.py's own module comment above _strategy_scan_counts and the
endpoint's own docstring for the full reasoning."""
import json
import os
import tempfile
import time
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _reset():
    main._strategy_scan_counts.clear()
    main._strategy_scan_counts_day = ""
    main._strategy_scan_recent_timestamps.clear()


def test_record_strategy_scan_counts_per_tag():
    _reset()
    main._record_strategy_scan("gap_and_go")
    main._record_strategy_scan("gap_and_go")
    main._record_strategy_scan("primary_base")
    assert main._strategy_scan_counts["gap_and_go"] == 2
    assert main._strategy_scan_counts["primary_base"] == 1


def test_record_strategy_scan_resets_on_day_rollover():
    _reset()
    with patch("main.ist_now") as mock_now:
        mock_now.return_value.strftime.return_value = "2026-10-01"
        main._record_strategy_scan("gap_and_go")
        assert main._strategy_scan_counts["gap_and_go"] == 1

        mock_now.return_value.strftime.return_value = "2026-10-02"
        main._record_strategy_scan("primary_base")
        assert "gap_and_go" not in main._strategy_scan_counts
        assert main._strategy_scan_counts["primary_base"] == 1


def test_scans_in_last_seconds_excludes_old_timestamps():
    _reset()
    now = time.time()
    main._strategy_scan_recent_timestamps["gap_and_go"] = [now - 60, now - 5]
    assert main._strategy_scans_in_last_seconds("gap_and_go") == 1


def test_endpoint_only_returns_currently_viable_strategies():
    _fresh_db()
    _reset()
    main._record_strategy_scan("gap_and_go")       # viable (gap_and_go_swing, PFnet 1.65)
    main._record_strategy_scan("minervini_vcp")    # NOT viable (PFnet 0.908, below floor)
    result = main.strategy_scan_activity()
    tags = {r["strategy_tag"] for r in result["strategies"]}
    assert "gap_and_go" in tags
    assert "minervini_vcp" not in tags


def test_endpoint_keeps_distinct_tags_separate_even_when_same_registry_entry():
    # Explicit user standing rule: a different tag name implies a real
    # variation and must never be silently merged. "orb-swing-gap-and-go"
    # and "gap_and_go" both map to gap_and_go_swing in
    # _STRATEGY_TAG_TO_REGISTRY_NAME - both must show up as their OWN row,
    # even though the former has zero other reference anywhere in main.py
    # (confirmed by grep) and will read scans_today=0 forever unless
    # something actually records scans under it.
    _fresh_db()
    _reset()
    main._record_strategy_scan("gap_and_go")
    result = main.strategy_scan_activity()
    tags_for_registry = {r["strategy_tag"]: r for r in result["strategies"]
                          if r["registry_name"] == "gap_and_go_swing"}
    assert set(tags_for_registry) == {"gap_and_go", "orb-swing-gap-and-go"}
    assert tags_for_registry["gap_and_go"]["scans_today"] == 1
    assert tags_for_registry["orb-swing-gap-and-go"]["scans_today"] == 0


def test_endpoint_counts_successful_entries_from_swing_trades_raw_payload():
    _fresh_db()
    _reset()
    main._record_strategy_scan("gap_and_go")
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
            (time.time(), "NYKAA.NS", 5, 180.0, 1.0, main.SWING_STRATEGY_TAG,
             json.dumps({"entry_reason": "gap_and_go", "stop_loss": 170.0})),
        )
        conn.commit()
    result = main.strategy_scan_activity()
    row = next(r for r in result["strategies"] if r["strategy_tag"] == "gap_and_go")
    assert row["successful_entries_today"] == 1


def test_endpoint_excludes_yesterdays_entries():
    _fresh_db()
    _reset()
    main._record_strategy_scan("gap_and_go")
    yesterday_ts = main.ist_midnight_epoch(main.ist_now()) - 3600  # before today's midnight
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
            (yesterday_ts, "NYKAA.NS", 5, 180.0, 1.0, main.SWING_STRATEGY_TAG,
             json.dumps({"entry_reason": "gap_and_go"})),
        )
        conn.commit()
    result = main.strategy_scan_activity()
    row = next(r for r in result["strategies"] if r["strategy_tag"] == "gap_and_go")
    assert row["successful_entries_today"] == 0


def test_endpoint_rows_carry_registry_categories():
    # Explicit user request (2026-10-05): the dashboard table gets a
    # leftmost Category column. Each row carries the registry's own
    # categories list (a strategy may sit on several - power_play is both
    # swing and buy), never a hardcoded label.
    _fresh_db()
    _reset()
    rows = {r["strategy_tag"]: r for r in main.strategy_scan_activity()["strategies"]}
    assert rows["gap_and_go"]["categories"] == ["swing"]
    assert rows["power_play"]["categories"] == ["swing", "buy"]


def test_endpoint_rows_carry_avg_held_hrs_from_registry_metrics():
    # Explicit user request (2026-10-05): one unit (market hours) for every
    # category. Daily-bar runs recorded avg held trading DAYS; stored as
    # days * 6.25 market hours/day. None where the run never recorded it.
    _fresh_db()
    _reset()
    rows = {r["strategy_tag"]: r for r in main.strategy_scan_activity()["strategies"]}
    assert rows["power_play"]["avg_held_hrs"] == round(16.2 * 6.25, 1)
    assert rows["primary_base"]["avg_held_hrs"] == round(17.0 * 6.25, 1)
    assert rows["order_block_delta"]["avg_held_hrs"] == round(23.2 * 6.25, 1)
    assert rows["volume_profile_poc"]["avg_held_hrs"] == round(13.2 * 6.25, 1)
    assert rows["minervini_vcp_livermore"]["avg_held_hrs"] == round(14.8 * 6.25, 1)
    assert rows["gap_and_go"]["avg_held_hrs"] is None  # run never recorded it - never guessed
