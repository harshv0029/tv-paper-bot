"""B-1576: once the day's Upstash budget is spent, non-exempt writes pause until the IST day rolls over."""
import pytest

import main


@pytest.fixture
def usage(monkeypatch):
    state = {"b": 0, "o": 0}
    monkeypatch.setattr(main, "_upstash_usage_totals", lambda: ({}, state["b"], state["o"]))
    monkeypatch.setattr(main, "_upstash_usage_day", "2026-11-16")
    return state


def test_below_budget_writes_pass(usage):
    usage["b"] = int(main._UPSTASH_DAILY_BYTES_BUDGET * 0.95)
    main._upstash_pause_check("tv_paper_bot:tbl:positions:v1:c0")
    assert main._UPSTASH_PAUSE["paused"] is False


def test_over_budget_pauses_noncritical(usage):
    usage["o"] = main._UPSTASH_DAILY_OPS_BUDGET
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("tv_paper_bot:tbl:swing_ltp_peak:v1:c0")
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("restart_tracker:heartbeat")
    assert main._UPSTASH_PAUSE["paused"] is True
    assert main._UPSTASH_PAUSE["skipped"]["tv_paper_bot:tbl:swing_ltp_peak:v1"] == 1
    with pytest.raises(main.UpstashPausedForDay):  # direct SET sites go through _upstash_set_url too
        main._upstash_set_url("tv_paper_bot:tbl:news_trades:v1:c0")


def test_real_money_state_exempt_until_hard_stop(usage):
    usage["b"] = main._UPSTASH_DAILY_BYTES_BUDGET
    for key in (main._REAL_POSITIONS_REDIS_KEY, main._REAL_POSITIONS_SWING_REDIS_KEY,
                "tv_paper_bot:tbl:trading_control:v1:meta", "tv_paper_bot:tbl:real_trades:v1:c0"):
        main._upstash_pause_check(key)
    usage["b"] = int(main._UPSTASH_DAILY_BYTES_BUDGET * main._UPSTASH_HARD_STOP_FRAC)
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check(main._REAL_POSITIONS_REDIS_KEY)


def test_new_day_unpauses(usage, monkeypatch):
    usage["o"] = main._UPSTASH_DAILY_OPS_BUDGET
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("tv_paper_bot:tbl:tracked_union:v1:c0")
    monkeypatch.setattr(main, "_upstash_usage_day", "2026-11-17")
    usage["o"] = 10
    main._upstash_pause_check("tv_paper_bot:tbl:tracked_union:v1:c0")
    assert main._UPSTASH_PAUSE == {"day": "2026-11-17", "paused": False, "since": None, "skipped": {}}


def test_set_refused_without_network(usage, monkeypatch):
    usage["o"] = main._UPSTASH_DAILY_OPS_BUDGET
    calls = []
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: calls.append(a))
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_set("tv_paper_bot:tbl:option_state:v1:c0", "{}")
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_del("tv_paper_bot:tbl:option_state:v1:c9")
    assert calls == []


def test_usage_endpoint_reports_pause(usage):
    usage["o"] = main._UPSTASH_DAILY_OPS_BUDGET
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("tv_paper_bot:tbl:option_state:v1:c0")
    out = main.upstash_usage()
    assert out["paused_for_day"] is True and out["writes_skipped_while_paused"]
