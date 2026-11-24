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
    keep = int((1 - main._UPSTASH_MONTH_RESERVE_FRAC) * main._UPSTASH_MONTHLY_BYTES)  # B-1691 reserve
    assert main._upstash_today_budget()[0] == max(0, keep - 30 * D)


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


def test_b1691_untracked_days_count_as_spent(usage, monkeypatch):
    monkeypatch.setattr(main, "_upstash_usage_day", "2026-11-24")
    monkeypatch.setattr(main, "_UPSTASH_OFFICIAL_CACHE", {"at": 0.0, "url": "", "data": None, "error": None})
    # live 2026-11-24: records from 11-14 only (4.4 GB), Upstash itself said 80%
    main._upstash_month_prior.update({f"2026-11-{d}": [440_000_000, 6000] for d in range(14, 24)})
    est_b, _ = main._upstash_month_prior_estimate()
    assert est_b == 4_400_000_000 + 13 * D
    assert main._upstash_today_budget()[0] == 0  # overspent: non-exempt writers stay paused


def test_b1691_month_cap_uses_estimate_and_reserve(usage, monkeypatch):
    monkeypatch.setattr(main, "_upstash_usage_day", "2026-11-28")
    monkeypatch.setattr(main, "_UPSTASH_OFFICIAL_CACHE", {"at": 0.0, "url": "", "data": None, "error": None})
    main._upstash_month_prior.update({f"2026-11-{d:02d}": [0, 0] for d in range(20, 28)})  # 19 untracked days
    keep = int((1 - main._UPSTASH_MONTH_RESERVE_FRAC) * main._UPSTASH_MONTHLY_BYTES)
    assert main._upstash_today_budget()[0] == min(9 * D, keep - 19 * D)


def test_b1691_official_figure_wins_when_larger(usage, monkeypatch):
    monkeypatch.setattr(main, "_UPSTASH_OFFICIAL_CACHE", {"at": 1.0, "url": main.UPSTASH_REDIS_REST_URL, "error": None,
                                                          "data": {"month_bandwidth_bytes": 9_600_000_000,
                                                                   "month_requests": 1000}})
    main._upstash_month_prior["2026-11-01"] = [0, 0]
    assert main._upstash_month_prior_estimate()[0] == 9_600_000_000
    assert main._upstash_today_budget()[0] == 0
