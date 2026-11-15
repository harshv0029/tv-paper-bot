"""B-1609 (user 2026-11-15): View 4 shows Upstash bandwidth used this month out of the 10 GB monthly limit."""
import pathlib

import main

HTML = pathlib.Path(__file__).resolve().parents[1] / "static" / "trade-view4.html"


def test_endpoint_reports_month_usage_vs_10gb(monkeypatch):
    monkeypatch.setattr(main, "_upstash_month_prior", {"2026-11-01": [1_000_000_000, 100], "2026-11-02": [500_000_000, 50]})
    out = main.upstash_usage()
    assert out["month_limit_bytes"] == 10_000_000_000
    assert out["month_used_bytes"] >= 1_500_000_000
    assert out["month_used_pct"] == round(100 * out["month_used_bytes"] / 10_000_000_000, 2)
    import calendar
    t = main.ist_now(); assert out["month_allowed_to_date_bytes"] == int(10_000_000_000 * t.day / calendar.monthrange(t.year, t.month)[1])
    assert out["month_used_ops"] >= 150 and out["month_limit_ops"] == 500_000


def test_view4_polls_and_shows_monthly_upstash_usage():
    s = HTML.read_text()
    assert 'getJSON("/upstash-usage")' in s and "setInterval(pollUpstash, 60000)" in s
    assert "month_allowed_to_date_bytes" in s and "month_used_bytes" in s and "10e9" in s
