"""B-1709: in Nov 2026 every Upstash HTTP call is refused outside market hours (user 2026-11-24, strict); after an
off-hours boot, writes stay held at the open until the Upstash restores re-ran. Run: pytest tests/test_b1709_upstash_offhours.py"""
import datetime as dt
import threading

import pytest
import requests

import main

D = dt.datetime


@pytest.mark.parametrize("t,zero", [
    (D(2026, 11, 24, 23, 10), True),   # Tue night
    (D(2026, 11, 24, 8, 59), True),    # before 09:00
    (D(2026, 11, 25, 9, 0), False),
    (D(2026, 11, 25, 15, 45), False),
    (D(2026, 11, 25, 15, 46), True),
    (D(2026, 11, 28, 11, 0), True),    # Saturday
    (D(2026, 12, 1, 23, 0), False),    # December: rule ends with November
])
def test_window(t, zero, monkeypatch):
    monkeypatch.setattr(main, "_UPSTASH_OFFHOURS_ZERO_MONTHS", frozenset({"2026-11"}))
    assert main._upstash_offhours_zero(t) is zero


def test_nse_holiday_weekday_is_off_hours(monkeypatch):
    monkeypatch.setattr(main, "_UPSTASH_OFFHOURS_ZERO_MONTHS", frozenset({"2026-11"}))
    monkeypatch.setattr(main, "_nse_calendar_trading_day", lambda d: False)
    monkeypatch.setattr(main, "nse_special_session", lambda t: None)
    assert main._upstash_offhours_zero(D(2026, 11, 25, 11, 0)) is True


def test_http_layer_refuses_every_upstash_call_off_hours(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: True)
    sent = []
    monkeypatch.setattr(main, "_requests_session_request_orig", lambda *a, **k: sent.append(a))
    for call in (lambda: requests.get("https://big-cat-1.upstash.io/get/k"),
                 lambda: requests.post("https://big-cat-1.upstash.io/set/k", data=b"x"),
                 lambda: requests.get("https://api.upstash.com/v2/redis/databases")):
        with pytest.raises(requests.exceptions.ConnectionError):
            call()
    requests.get("https://example.com/x")  # other hosts untouched
    assert len(sent) == 1 and main._UPSTASH_OFFHOURS["by_kind"].get("off_hours", 0) >= 3
    # the real-money writer degrades exactly like an unreachable Upstash: no raise into the order path
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://big-cat-1.upstash.io")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    with main.closing(main.get_db()) as c:
        main._sync_real_positions_external(c)


def test_writes_held_until_restore_after_offhours_boot(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: False)
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "catchup_pending", True)
    u = "https://big-cat-1.upstash.io"
    assert main._upstash_offhours_block_kind("POST", u + "/set/k") == "await_restore"
    assert main._upstash_offhours_block_kind("GET", u + "/get/k") is None
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "catchup_thread", threading.get_ident())
    assert main._upstash_offhours_block_kind("POST", u + "/set/k") is None  # the restore thread itself


def test_catchup_runs_restores_then_releases(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: False)
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "catchup_pending", True)
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "slot_select_deferred", False)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://big-cat-1.upstash.io")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    ran = []
    for n in ("hydrate_runtime_settings_from_external", "hydrate_t1_restricted_from_external"):
        monkeypatch.setattr(main, n, lambda conn, n=n: ran.append(n))
    for n in ("hydrate_real_positions_from_external", "hydrate_real_positions_short_from_external",
              "hydrate_real_positions_swing_from_external", "hydrate_check_totals_daily",
              "hydrate_signal_state_swing_from_external", "hydrate_generic_tables_from_external",
              "hydrate_real_open_positions_last_good_from_external", "hydrate_swing_skipped_from_external",
              "hydrate_exit_timing_from_external", "_startup_merge_viable_stack"):
        monkeypatch.setattr(main, n, lambda n=n: ran.append(n))
    monkeypatch.setattr(main.instance_lease, "claim_at_startup", lambda: "leader")
    probe = {"ok": False}
    monkeypatch.setattr(main, "_upstash_probe", lambda: probe)
    assert main._upstash_offhours_catchup() is True
    assert main._UPSTASH_OFFHOURS["catchup_pending"] is True  # Upstash down at the open: keep holding writes
    probe["ok"] = True
    ran.clear()
    assert main._upstash_offhours_catchup() is True
    assert len(ran) == 12 and "hydrate_real_positions_swing_from_external" in ran
    assert main._UPSTASH_OFFHOURS["catchup_pending"] is False and main._UPSTASH_OFFHOURS["catchup_thread"] is None
    assert main._upstash_offhours_catchup() is False  # once only


def test_catchup_waits_for_the_window(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: True)
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "catchup_pending", True)
    assert main._upstash_offhours_catchup() is False


def test_probe_does_not_ping_off_hours(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: True)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://big-cat-1.upstash.io")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pinged")))
    assert main._upstash_probe()["paused_offhours"] is True


def test_slot_choice_deferred_off_hours(monkeypatch):
    monkeypatch.setattr(main, "_upstash_offhours_zero", lambda now=None: True)
    monkeypatch.setitem(main._UPSTASH_OFFHOURS, "slot_select_deferred", False)
    env = {"UPSTASH_REDIS_REST_URL_1": "https://a.upstash.io", "UPSTASH_REDIS_REST_TOKEN_1": "t"}
    monkeypatch.setattr(main.os, "environ", env)
    assert main._upstash_select_slot_at_boot() is None and main._UPSTASH_OFFHOURS["slot_select_deferred"] is True


def test_production_months_cover_november_only():
    import importlib, ast, os
    src = open(os.path.join(os.path.dirname(__file__), "..", "main.py")).read()
    assert '_UPSTASH_OFFHOURS_ZERO_MONTHS = frozenset({"2026-11"})' in src
