"""B-1577: cumulative Upstash quota. Today's budget = daily budget + earlier days' leftover (or minus overspend)."""
import pytest

import main

D = main._UPSTASH_DAILY_BYTES_BUDGET


@pytest.fixture
def usage(monkeypatch):
    state = {"b": 0, "o": 0}
    monkeypatch.setattr(main, "_upstash_usage_totals", lambda: ({}, state["b"], state["o"]))
    monkeypatch.setattr(main, "_upstash_usage_day", "2026-11-02")
    monkeypatch.setattr(main, "_upstash_month_prior", {})
    return state


def test_overspend_carries_into_next_day(usage):
    main._upstash_month_prior["2026-11-01"] = [D + 2_000_000, 100]  # user's example: 302 of 300
    assert main._upstash_today_budget()[0] == D - 2_000_000
    usage["b"] = D - 3_000_000
    main._upstash_pause_check("tv_paper_bot:tbl:tracked_union:v1:r0")  # 2-day total still under 2 x budget
    usage["b"] = D - 2_000_000  # 2-day total == 2 x budget -> pause
    with pytest.raises(main.UpstashPausedForDay):
        main._upstash_pause_check("tv_paper_bot:tbl:tracked_union:v1:r0")


def test_unused_quota_rolls_forward_but_month_cap_holds(usage):
    main._upstash_month_prior.update({"2026-11-01": [0, 0]})
    assert main._upstash_today_budget()[0] == 2 * D
    main._upstash_month_prior.update({f"2026-11-{d:02d}": [D, 0] for d in range(1, 31)})
    assert main._upstash_today_budget()[0] == max(0, main._UPSTASH_MONTHLY_BYTES - 30 * D)


def test_no_history_is_plain_daily_budget(usage):
    assert main._upstash_today_budget() == (D, main._UPSTASH_DAILY_OPS_BUDGET)


def test_month_load_finalises_previous_day_and_drops_other_months():
    prev = {"day": "2026-11-01", "families": {"a": {"get_ops": 2, "get_bytes": 10, "set_ops": 3, "set_bytes": 5}},
            "month_days": {"2026-10-31": [9, 9]}}
    main._upstash_month_load(prev, "2026-11-02")
    assert main._upstash_month_prior == {"2026-11-01": [15, 5]}
    main._upstash_month_load({"day": "2026-11-02", "families": {}, "month_days": {"2026-11-01": [15, 5]}},
                             "2026-11-02")
    assert main._upstash_month_prior == {"2026-11-01": [15, 5]}
