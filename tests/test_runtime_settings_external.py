"""Tests for the runtime_settings Upstash persistence fix (2026-09-09,
explicit user finding: "When I updated batch per ticker to be from 35 to
100, why it is getting reset to 35 again. Have u not made this overwrite
previous value by taking input from front end?"). Unlike real_positions/
rr_cursor/check_counts (each fixed earlier the same way), the
runtime_settings SQLite table had NO external mirror at all - any value
set via POST /runtime-settings reverted to RUNTIME_SETTINGS_META's
hardcoded default on the next restart. See main.py's "runtime_settings
external persistence" module comment."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_sync_no_ops_silently_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.requests.post") as mock_post:
            main._sync_runtime_settings_external(conn)
            mock_post.assert_not_called()


def test_sync_pushes_the_full_table_snapshot_to_upstash():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            conn.execute(
                "INSERT INTO runtime_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, 'user')",
                ("entry_scan_batch_size", 100.0, 123.0),
            )
            conn.commit()
            with patch("main.requests.post") as mock_post:
                main._sync_runtime_settings_external(conn)
                mock_post.assert_called_once()
                call = mock_post.call_args
                assert call.args[0] == "https://fake-upstash.example.com/set/tv_paper_bot:runtime_settings:v1"
                assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
                import json as json_mod
                body = json_mod.loads(call.kwargs["data"])
                assert body == {"entry_scan_batch_size": 100.0}
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_sync_failure_is_swallowed_not_raised():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            with patch("main.requests.post", side_effect=Exception("connection refused")):
                main._sync_runtime_settings_external(conn)  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_0_when_env_vars_unset():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.requests.get") as mock_get:
            assert main.hydrate_runtime_settings_from_external(conn) == 0
            mock_get.assert_not_called()


def test_hydrate_writes_restored_keys_into_the_table_and_get_runtime_setting_sees_them():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": json_mod.dumps({"entry_scan_batch_size": 100.0, "daily_risk_pct": 3.0}),
        }
        mock_resp.raise_for_status.return_value = None
        with closing(main.get_db()) as conn:
            with patch("main.requests.get", return_value=mock_resp):
                restored = main.hydrate_runtime_settings_from_external(conn)
            assert restored == 2
            assert main.get_runtime_setting(conn, "entry_scan_batch_size") == 100.0
            assert main.get_runtime_setting(conn, "daily_risk_pct") == 3.0
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_skips_a_key_no_longer_in_runtime_settings_meta():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": json_mod.dumps({"entry_scan_batch_size": 100.0, "some_removed_setting": 5.0}),
        }
        mock_resp.raise_for_status.return_value = None
        with closing(main.get_db()) as conn:
            with patch("main.requests.get", return_value=mock_resp):
                restored = main.hydrate_runtime_settings_from_external(conn)
            assert restored == 1
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_hydrate_returns_0_on_empty_or_malformed_or_failed_read():
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        with closing(main.get_db()) as conn:
            empty_resp = MagicMock()
            empty_resp.json.return_value = {"result": None}
            empty_resp.raise_for_status.return_value = None
            with patch("main.requests.get", return_value=empty_resp):
                assert main.hydrate_runtime_settings_from_external(conn) == 0

            with patch("main.requests.get", side_effect=Exception("timeout")):
                assert main.hydrate_runtime_settings_from_external(conn) == 0  # must not raise
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None


def test_set_runtime_setting_endpoint_syncs_to_upstash_after_commit():
    """End-to-end: POST /runtime-settings must push the updated table to
    Upstash, not just write it to the (ephemeral) local SQLite table -
    exactly the gap the user found live."""
    _fresh_db()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        from unittest.mock import MagicMock as _MM
        fake_request = _MM()
        with patch("main.requests.post") as mock_post:
            result = main.set_runtime_setting(fake_request, "entry_scan_batch_size", 100.0)
            assert result["status"] == "saved"
            mock_post.assert_called_once()
            import json as json_mod
            body = json_mod.loads(mock_post.call_args.kwargs["data"])
            assert body.get("entry_scan_batch_size") == 100.0
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
