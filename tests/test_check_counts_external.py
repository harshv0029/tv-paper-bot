"""Tests for the scheduler check_counts Upstash persistence fix
(2026-09-09, explicit user finding: "751 total checks run today (751 /
2661 distinct)... these two numbers are getting reset again. why so?
have u not fixed?"). The earlier 2026-09-08 rr_cursor fix only covered
the round-robin CURSOR (an int) - the check_counts dict itself (per-
symbol counts, what "distinct scanned" is actually computed from) was
still only journal-persisted every ~15 min, so a restart happening more
often than that kept wiping it back to empty. See main.py's
"check_counts (the 'distinct symbols scanned today' state)" module
comment."""
from unittest.mock import MagicMock, patch

import main


def test_sync_no_ops_silently_when_env_vars_unset():
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with patch("main.requests.post") as mock_post:
        main._sync_check_counts_external("2026-09-09", {"RELIANCE.NS": 3})
        mock_post.assert_not_called()


def test_sync_pushes_the_day_and_counts_dict_to_upstash():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.post") as mock_post:
            main._sync_check_counts_external("2026-09-09", {"RELIANCE.NS": 3, "TCS.NS": 1})
            mock_post.assert_called_once()
            call = mock_post.call_args
            assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:scheduler_check_counts:v1"
            assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
            import json as json_mod
            body = json_mod.loads(call.kwargs["data"])
            assert body == {"day": "2026-09-09", "counts": {"RELIANCE.NS": 3, "TCS.NS": 1}}
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.post", side_effect=Exception("connection refused")):
            main._sync_check_counts_external("2026-09-09", {"RELIANCE.NS": 3})  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_none_when_env_vars_unset():
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with patch("main.requests.get") as mock_get:
        assert main.hydrate_check_counts_from_external() is None
        mock_get.assert_not_called()


def test_hydrate_returns_the_saved_day_and_counts():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": json_mod.dumps({"day": "2026-09-09", "counts": {"RELIANCE.NS": 5}}),
        }
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            assert main.hydrate_check_counts_from_external() == ("2026-09-09", {"RELIANCE.NS": 5})
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_none_on_empty_missing_or_malformed_read():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        import json as json_mod
        empty_resp = MagicMock()
        empty_resp.json.return_value = {"result": None}
        empty_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=empty_resp):
            assert main.hydrate_check_counts_from_external() is None

        malformed_resp = MagicMock()
        malformed_resp.json.return_value = {"result": json_mod.dumps({"day": "2026-09-09", "counts": "not-a-dict"})}
        malformed_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=malformed_resp):
            assert main.hydrate_check_counts_from_external() is None

        with patch("main.requests.get", side_effect=Exception("timeout")):
            assert main.hydrate_check_counts_from_external() is None  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_journal_reconcile_never_clobbers_an_already_restored_check_counts_dict(tmp_path):
    """Regression test for the exact bug: Upstash restores a fresh counts
    dict first, then the slower git-journal reconcile must not overwrite/
    merge over it with its own, staler snapshot."""
    journal_path = tmp_path / "scheduler_check_counts.json"
    journal_path.write_text(
        '{"day": "2026-09-09", "rr_cursor": 50, "counts": {"STALE.NS": 999}}'
    )
    main.STATE_SCHEDULER_CHECK_COUNTS_PATH = str(journal_path)
    main._scheduler_check_counts.clear()
    main._scheduler_check_counts.update({"RELIANCE.NS": 12, "TCS.NS": 7})  # already restored from Upstash
    main._scheduler_check_counts_day = "2026-09-09"
    try:
        with patch("main.ist_now") as mock_now:
            mock_now.return_value.strftime.return_value = "2026-09-09"
            main.reconcile_scheduler_check_counts_from_journal()
        assert main._scheduler_check_counts == {"RELIANCE.NS": 12, "TCS.NS": 7}, \
            "a fresher Upstash-restored counts dict must survive the journal reconcile untouched"
    finally:
        main._scheduler_check_counts.clear()
        main._scheduler_check_counts_day = ""


def test_journal_reconcile_still_restores_when_check_counts_is_still_empty(tmp_path):
    """Sanity check the fix doesn't break the original fallback - when
    Upstash provided nothing (dict still empty), the journal must still
    restore its own saved counts."""
    journal_path = tmp_path / "scheduler_check_counts.json"
    journal_path.write_text(
        '{"day": "2026-09-09", "rr_cursor": 50, "counts": {"RELIANCE.NS": 3}}'
    )
    main.STATE_SCHEDULER_CHECK_COUNTS_PATH = str(journal_path)
    main._scheduler_check_counts.clear()
    main._scheduler_check_counts_day = ""
    try:
        with patch("main.ist_now") as mock_now:
            mock_now.return_value.strftime.return_value = "2026-09-09"
            main.reconcile_scheduler_check_counts_from_journal()
        assert main._scheduler_check_counts == {"RELIANCE.NS": 3}
        assert main._scheduler_check_counts_day == "2026-09-09"
    finally:
        main._scheduler_check_counts.clear()
        main._scheduler_check_counts_day = ""
