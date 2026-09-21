"""Tests for the memory-visibility instrumentation (2026-09-21, explicit
user instruction after a Render "exceeded its memory limit" restart
email: "can u find root cause and set limit on things required so that
this does not come into my email inbox every now n then"). The
previously-fixed leak (_DATA_CACHE, data_fetch.py) is confirmed still
fixed and even safer now (WATCHLIST shrank from ~2,661 to 206 symbols
since that fix), and a live restart was directly observed (a 502 from
the deployed service, recovered within ~2 minutes) - but pinning down a
NEW leak needs actual memory data over time, which didn't exist before
this. This just adds that visibility (RSS, stdlib-only via `resource`),
both on /health and (see main.py's own scheduler-tick comment) logged
periodically."""
import main


def test_process_rss_mb_returns_a_positive_number():
    rss = main._process_rss_mb()
    assert rss is not None
    assert rss > 0


def test_health_endpoint_reports_rss_mb():
    result = main.health()
    assert result["status"] == "alive"
    assert "rss_mb" in result
    assert result["rss_mb"] > 0
