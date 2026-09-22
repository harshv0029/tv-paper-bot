"""Tests for the 2026-09-22 fix: the real daily buy-notional cap
(real_daily_cap_inr) must default to the LIVE Kotak account balance, not
a hardcoded Rs 2000 - explicit user instruction: "The cap should be based
on money available in trading account. Hard coding should not be done at
all... Capital to be invested should be live from amount available in
trading account." A manual override (POST /runtime-settings) must still
win over live tracking once the user sets one, same as every other
runtime_setting.

Run: pytest tests/test_real_daily_cap_live.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_no_override_row_tracks_live_capital():
    _fresh_db()
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=54321.0):
            assert main._effective_real_daily_cap_inr(conn) == 54321.0


def test_no_override_row_follows_live_capital_as_it_moves_not_frozen():
    _fresh_db()
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", side_effect=[10000.0, 25000.0]):
            first = main._effective_real_daily_cap_inr(conn)
            second = main._effective_real_daily_cap_inr(conn)
        assert first == 10000.0
        assert second == 25000.0  # re-read live each call, not cached/frozen by this function


def test_no_successful_live_fetch_ever_blocks_rather_than_fabricating_a_number():
    _fresh_db()
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=0.0):
            assert main._effective_real_daily_cap_inr(conn) == 0.0  # not REAL_TRADING_DAILY_CAP_INR


def test_explicit_override_row_wins_over_live_capital():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO runtime_settings (key, value, updated_at, updated_by) "
            "VALUES ('real_daily_cap_inr', 500.0, ?, 'user')", (main.time.time(),),
        )
        conn.commit()
        with patch("main.get_scheduler_capital_inr", return_value=999999.0):
            assert main._effective_real_daily_cap_inr(conn) == 500.0  # live capital ignored


def test_override_persists_across_calls_until_changed_again():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO runtime_settings (key, value, updated_at, updated_by) "
            "VALUES ('real_daily_cap_inr', 750.0, ?, 'user')", (main.time.time(),),
        )
        conn.commit()
        with patch("main.get_scheduler_capital_inr", side_effect=[111.0, 222.0]):
            assert main._effective_real_daily_cap_inr(conn) == 750.0
            assert main._effective_real_daily_cap_inr(conn) == 750.0  # still 750, not live-tracked


def test_other_runtime_settings_keys_are_unaffected():
    _fresh_db()
    with closing(main.get_db()) as conn:
        assert main.get_runtime_setting(conn, "entry_scan_batch_size") == 35.0


def test_get_runtime_settings_endpoint_reports_live_value_for_this_key_when_unset():
    _fresh_db()
    with patch("main.get_scheduler_capital_inr", return_value=87654.0):
        result = main.get_runtime_settings()
    assert result["real_daily_cap_inr"]["value"] == 87654.0
    assert result["real_daily_cap_inr"]["default"] == main.REAL_TRADING_DAILY_CAP_INR


def test_get_runtime_settings_endpoint_reports_the_override_when_set():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO runtime_settings (key, value, updated_at, updated_by) "
            "VALUES ('real_daily_cap_inr', 300.0, ?, 'user')", (main.time.time(),),
        )
        conn.commit()
    with patch("main.get_scheduler_capital_inr", return_value=87654.0):
        result = main.get_runtime_settings()
    assert result["real_daily_cap_inr"]["value"] == 300.0


def test_real_trading_control_endpoint_uses_live_cap_when_unset():
    _fresh_db()
    with patch("main.get_scheduler_capital_inr", return_value=42000.0), \
         patch("main._require_kotak_token", return_value=None):
        result = main.get_real_trading_control(request=None)
    assert result["daily_cap_inr"] == 42000.0
