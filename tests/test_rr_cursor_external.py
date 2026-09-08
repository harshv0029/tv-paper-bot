"""Tests for the rr_cursor Upstash persistence fix (2026-09-08, explicit
user finding: "how to get this cover all the assets every 15 min... any
resource is a constraint or bottleneck now?"). Live diagnostic that day
showed rr_cursor back at 0 mid-afternoon despite the trading session being
hours old - traced to the same restart-race family as real_positions,
just for the round-robin scan cursor. See main.py's
"Scan-coverage external persistence" comment block."""
from unittest.mock import MagicMock, patch

import main


def test_sync_no_ops_silently_when_env_vars_unset():
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with patch("main.requests.post") as mock_post:
        main._sync_rr_cursor_external(1085)
        mock_post.assert_not_called()


def test_sync_pushes_the_cursor_value_to_upstash():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.post") as mock_post:
            main._sync_rr_cursor_external(1085)
            mock_post.assert_called_once()
            call = mock_post.call_args
            assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:rr_cursor:v1"
            assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
            assert call.kwargs["data"] == b"1085"
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with patch("main.requests.post", side_effect=Exception("connection refused")):
            main._sync_rr_cursor_external(1085)  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_none_when_env_vars_unset():
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with patch("main.requests.get") as mock_get:
        assert main.hydrate_rr_cursor_from_external() is None
        mock_get.assert_not_called()


def test_hydrate_returns_the_saved_cursor_value():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "1085"}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            assert main.hydrate_rr_cursor_from_external() == 1085
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_none_on_empty_or_failed_read():
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": None}
        mock_resp.raise_for_status.return_value = None
        with patch("main.requests.get", return_value=mock_resp):
            assert main.hydrate_rr_cursor_from_external() is None
        with patch("main.requests.get", side_effect=Exception("timeout")):
            assert main.hydrate_rr_cursor_from_external() is None  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_journal_reconcile_never_clobbers_an_already_restored_cursor(tmp_path):
    """Regression test for the exact bug: Upstash restores a fresh cursor
    first, then the slower git-journal reconcile must not overwrite it
    with its own, staler snapshot."""
    journal_path = tmp_path / "scheduler_check_counts.json"
    journal_path.write_text('{"day": "2099-01-01", "rr_cursor": 50, "counts": {}}')
    main.STATE_SCHEDULER_CHECK_COUNTS_PATH = str(journal_path)
    main._scheduler_rr_cursor = 1085  # already restored from Upstash by the caller
    try:
        main.reconcile_scheduler_check_counts_from_journal()
        assert main._scheduler_rr_cursor == 1085, "a fresher Upstash-restored cursor must survive the journal reconcile"
    finally:
        main._scheduler_rr_cursor = 0


def test_journal_reconcile_still_restores_when_cursor_is_still_zero(tmp_path):
    """Sanity check the fix doesn't break the original fallback - when
    Upstash provided nothing (cursor still at its default 0), the journal
    must still restore its own saved value."""
    journal_path = tmp_path / "scheduler_check_counts.json"
    journal_path.write_text('{"day": "2099-01-01", "rr_cursor": 512, "counts": {}}')
    main.STATE_SCHEDULER_CHECK_COUNTS_PATH = str(journal_path)
    main._scheduler_rr_cursor = 0
    try:
        main.reconcile_scheduler_check_counts_from_journal()
        assert main._scheduler_rr_cursor == 512
    finally:
        main._scheduler_rr_cursor = 0
