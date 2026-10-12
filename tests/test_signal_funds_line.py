"""B-868: 'available = X, need = Y' for non-green signals (/signal-funds)."""
import datetime as dt
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def test_line_format_and_unknown():
    assert main._funds_line(5000, 1200) == "available = Rs 5,000, need = Rs 1,200"
    assert main._funds_line(None, None) == "available = unknown, need = unknown"


def test_non_green_classifier():
    assert main._is_non_green_action("insufficient_capital")
    assert main._is_non_green_action("skipped_t1_restricted")
    assert not main._is_non_green_action("entered_long")
    assert not main._is_non_green_action("none")


def test_fail_soft_when_kotak_unreadable():
    saved = dict(main._real_capital_cache)
    try:
        main._real_capital_cache.update(value=None, fetched_at=0.0, error=None)
        with patch("kotak_neo.limits", side_effect=RuntimeError("down")):
            assert main._available_money_now() is None
    finally:
        main._real_capital_cache.update(saved)


def test_endpoint_equity_and_fo():
    main._scheduler_last_results["ZZTEST.NS"] = {"action_taken": "insufficient_capital", "need_inr": 1500.0,
                                                  "checked_at_utc": 1.0}
    main._scheduler_last_results["OKTEST.NS"] = {"action_taken": "entered_long", "checked_at_utc": 1.0}
    main._fo_strike_monitor.clear()
    main._fo_strike_monitor["X"] = {"underlying": "NIFTY", "lot_size": 75, "last_close": 100.0}
    fake_diag = {"underlyings": {"NIFTY": {"primary_blocker": "real_fo_switch_off"},
                                 "BANKNIFTY": {"primary_blocker": "none_detected"}}}
    try:
        with patch.object(main, "_available_money_now", return_value=9000.0), \
             patch.object(main, "fo_entry_diagnosis", return_value=fake_diag), \
             patch.object(main, "ist_now", return_value=dt.datetime(2026, 10, 12, 11, 0)):
            d = TestClient(main.app).get("/signal-funds").json()
    finally:
        main._scheduler_last_results.pop("ZZTEST.NS", None)
        main._scheduler_last_results.pop("OKTEST.NS", None)
        main._fo_strike_monitor.clear()
    assert d["equity"]["ZZTEST.NS"]["line"] == "available = Rs 9,000, need = Rs 1,500"
    assert "OKTEST.NS" not in d["equity"]
    assert d["fo"]["NIFTY"]["line"] == "available = Rs 9,000, need = Rs 7,500"
    assert "BANKNIFTY" not in d["fo"]
