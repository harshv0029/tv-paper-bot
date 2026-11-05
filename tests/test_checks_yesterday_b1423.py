"""B-1423: 'checks yesterday' under 'checks today' - daily totals survive the day rollover and restarts."""
import json
from unittest.mock import patch

import main


def _reset():
    main._check_totals_daily.clear()


def test_merge_keeps_larger_total_and_recent_days():
    _reset()
    main._check_totals_merge({"2026-10-28": 100})
    main._check_totals_merge({"2026-10-28": 90, "2026-10-27": "bad", "2026-10-26": 5})
    assert main._check_totals_daily == {"2026-10-28": 100, "2026-10-26": 5}
    assert main._CHECK_TOTALS_KEEP_DAYS >= 3650  # B-1487: all-time history for "max till date"
    import datetime as _d
    many = {(_d.date(2010, 1, 1) + _d.timedelta(days=k)).isoformat(): 1 for k in range(main._CHECK_TOTALS_KEEP_DAYS + 5)}
    main._check_totals_merge(many)
    assert len(main._check_totals_daily) == main._CHECK_TOTALS_KEEP_DAYS
    assert "2026-10-28" in main._check_totals_daily
    _reset()


def test_previous_day_labels_yesterday_or_an_older_day():
    _reset()
    main._check_totals_merge({"2026-10-28": 186344, "2026-10-29": 5})
    assert main._checks_previous_day("2026-10-29") == {"day": "2026-10-28", "total": 186344, "is_yesterday": True}
    assert main._checks_previous_day("2026-11-02")["is_yesterday"] is False  # Monday after a weekend
    assert main._checks_previous_day("2026-10-01") == {}
    _reset()


def test_rollover_keeps_the_closing_days_total():
    _reset()
    saved_counts, saved_day = dict(main._scheduler_check_counts), main._scheduler_check_counts_day
    try:
        main._scheduler_check_counts.clear()
        main._scheduler_check_counts.update({"A.NS": 3, "X:OPT": 2})
        main._scheduler_check_counts_day = "2026-10-28"
        with patch.object(main, "_check_totals_push", lambda: None), \
             patch.object(main, "ist_now", return_value=main.dt.datetime(2026, 10, 29, 9, 15)):
            main._record_scheduler_check("B.NS")
        assert main._check_totals_daily["2026-10-28"] == 5
        assert main._scheduler_check_counts == {"B.NS": 1}
    finally:
        main._scheduler_check_counts.clear()
        main._scheduler_check_counts.update(saved_counts)
        main._scheduler_check_counts_day = saved_day
        _reset()


def test_hydrate_reads_git_backfill_and_upstash():
    _reset()
    with patch.object(main, "UPSTASH_REDIS_REST_URL", "u"), patch.object(main, "UPSTASH_REDIS_REST_TOKEN", "t"), \
         patch.object(main, "_upstash_get", return_value=json.dumps({"2026-10-28": 200000, "2026-10-27": 7})):
        main.hydrate_check_totals_daily()
    assert main._check_totals_daily["2026-10-28"] == 200000 and main._check_totals_daily["2026-10-27"] == 7
    _reset()
    with open(main._CHECK_TOTALS_BACKFILL_PATH) as f:
        assert json.load(f)["2026-10-28"] == 186344


def test_dashboard_shows_checks_yesterday():
    html = open("static/trade-view4.html").read()
    assert 'checks yesterday <b id="cyday">' in html and "checks_previous_day" in html
    assert html.index('id="ctoday"') < html.index('id="cyday"')
    assert '"checks_previous_day": _checks_previous_day(' in open(main.__file__).read()


def test_max_till_date_and_journal_floor_b1487():
    _reset()
    main._check_totals_merge({"2026-10-29": 680000, "2026-11-04": 389349})
    assert main._checks_max_till_date("2026-11-05", 100) == {"day": "2026-10-29", "total": 680000}
    assert main._checks_max_till_date("2026-11-05", 700000) == {"day": "2026-11-05", "total": 700000}
    # the git counts journal is a floor for its day (a restart cannot lower a day's total)
    j = json.dumps({"day": "2026-11-04", "counts": {"A.NS": 479000, "B.NS": 110}})
    from unittest.mock import mock_open
    real_open = open

    def fake_open(path, *a, **k):
        if path == main.STATE_SCHEDULER_CHECK_COUNTS_PATH:
            return mock_open(read_data=j)()
        return real_open(path, *a, **k)
    with patch("builtins.open", side_effect=fake_open), patch.object(main, "UPSTASH_REDIS_REST_URL", ""):
        main.hydrate_check_totals_daily()
    assert main._check_totals_daily["2026-11-04"] == 479110
    _reset()
    html = open("static/trade-view4.html").read()
    assert "max till date = " in html and "checks_max_till_date" in html
    assert '"checks_max_till_date": _checks_max_till_date(' in open(main.__file__).read()
