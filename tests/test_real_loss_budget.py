"""Tests for the joint real daily-loss cap fix (2026-09-08, explicit user
instruction: "keep it as a % of total money available at the beginning of
day. kotak balance" - a FIXED day-open capital basis, shared/joint across
equity and F&O, not a separate figure per asset class that also drifted
throughout the day). See main.py's _day_open_capital_inr/_real_loss_budget
docstrings and the module comment above them."""
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


def _reset_day_open_cache():
    main._day_open_capital_cache["day"] = None
    main._day_open_capital_cache["value"] = None


def test_day_open_capital_captures_once_and_caches_in_memory():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", side_effect=[100000.0, 999999.0]) as mock_cap:
            first = main._day_open_capital_inr(conn)
            second = main._day_open_capital_inr(conn)
            assert first == 100000.0
            assert second == 100000.0, "must NOT re-capture a fresh (different) value on the same day"
            assert mock_cap.call_count == 1


def test_day_open_capital_prefers_upstash_over_a_fresh_capture():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        today = main.ist_now().strftime("%Y-%m-%d")
        from unittest.mock import MagicMock
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json_mod.dumps({"day": today, "value": 55000.0})}
        mock_resp.raise_for_status.return_value = None
        with closing(main.get_db()) as conn:
            with patch("main.requests.get", return_value=mock_resp), \
                 patch("main.get_scheduler_capital_inr") as mock_cap:
                value = main._day_open_capital_inr(conn)
                assert value == 55000.0
                mock_cap.assert_not_called()
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
        _reset_day_open_cache()


def test_day_open_capital_ignores_a_stale_prior_day_upstash_snapshot():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = "https://fake-upstash.example.com"
    main.UPSTASH_REDIS_REST_TOKEN = "fake-token"
    try:
        from unittest.mock import MagicMock
        import json as json_mod
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": json_mod.dumps({"day": "2020-01-01", "value": 55000.0})}
        mock_resp.raise_for_status.return_value = None
        with closing(main.get_db()) as conn:
            with patch("main.requests.get", return_value=mock_resp), \
                 patch("main.requests.post"), \
                 patch("main.get_scheduler_capital_inr", return_value=200000.0) as mock_cap:
                value = main._day_open_capital_inr(conn)
                assert value == 200000.0, "a stale prior-day snapshot must never be used as today's basis"
                mock_cap.assert_called_once()
    finally:
        main.UPSTASH_REDIS_REST_URL = None
        main.UPSTASH_REDIS_REST_TOKEN = None
        _reset_day_open_cache()


def test_real_loss_budget_ok_when_under_cap():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=100000.0), \
             patch("main.get_real_pnl_today_inr", return_value=-500.0):
            # daily_risk_pct default is 2.0 -> cap = 100000*0.02 = 2000
            result = main._real_loss_budget(conn)
            assert result["ok"] is True
            assert result["cap_inr"] == 2000.0
            assert result["day_open_capital_inr"] == 100000.0


def test_real_loss_budget_blocks_when_loss_hits_cap():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=100000.0), \
             patch("main.get_real_pnl_today_inr", return_value=-2500.0):
            result = main._real_loss_budget(conn)
            assert result["ok"] is False
            assert "joint cap" in result["detail"]


def test_real_loss_budget_fails_closed_on_unknown_pnl():
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=100000.0), \
             patch("main.get_real_pnl_today_inr", return_value=None):
            result = main._real_loss_budget(conn)
            assert result["ok"] is False
            assert result["real_pnl_today"] is None


def test_real_loss_budget_uses_fixed_day_open_capital_not_live_capital():
    """The exact behavior the user asked for: once captured, the cap must
    NOT drift even if the live (post-loss) capital figure has since
    dropped - a live-refreshing basis would otherwise make the cap keep
    shrinking as losses accrue, a moving target."""
    _fresh_db()
    _reset_day_open_cache()
    main.UPSTASH_REDIS_REST_URL = None
    main.UPSTASH_REDIS_REST_TOKEN = None
    with closing(main.get_db()) as conn:
        with patch("main.get_scheduler_capital_inr", return_value=100000.0), \
             patch("main.get_real_pnl_today_inr", return_value=-100.0):
            first = main._real_loss_budget(conn)
            assert first["cap_inr"] == 2000.0
        # Live capital has since dropped a lot (money moved into open
        # positions, or losses realized) - the cap basis must stay fixed.
        with patch("main.get_scheduler_capital_inr", return_value=1000.0), \
             patch("main.get_real_pnl_today_inr", return_value=-500.0):
            second = main._real_loss_budget(conn)
            assert second["cap_inr"] == 2000.0, "cap must stay fixed at the day-open value, not track live capital"
            assert second["day_open_capital_inr"] == 100000.0
