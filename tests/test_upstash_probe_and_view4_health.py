import asyncio
"""B-1357: a dead Upstash or Render must show red on trade-view4, never a stale 'no error'."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import main


def test_probe_records_403_as_failure(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    r = MagicMock(status_code=403, content=b"suspended", text="ERR max bandwidth exceeded")
    with patch.object(main.requests, "get", return_value=r):
        p = main._upstash_probe(now=100.0)
    assert p["ok"] is False and "403" in p["error"]


def test_probe_ok_sets_last_ok(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    r = MagicMock(status_code=200, content=b'{"result":"PONG"}', text="PONG")
    with patch.object(main.requests, "get", return_value=r):
        p = main._upstash_probe(now=200.0)
    assert p["ok"] is True and p["error"] is None and p["last_ok_at"] == 200.0


def test_probe_never_raises_on_network_error(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    with patch.object(main.requests, "get", side_effect=OSError("timeout")):
        p = main._upstash_probe(now=300.0)
    assert p["ok"] is False and "timeout" in p["error"]


def test_probe_retries_one_timeout(monkeypatch):
    """B-1360: a single ReadTimeout (live 17:55 IST, during the boot restore) must not paint Upstash red."""
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    ok = MagicMock(status_code=200, content=b"PONG", text="PONG")
    with patch.object(main.requests, "get", side_effect=[OSError("ReadTimeout"), ok]) as g:
        p = main._upstash_probe(now=400.0)
    assert p["ok"] is True and g.call_count == 2


def test_probe_does_not_retry_http_error(monkeypatch):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    r = MagicMock(status_code=403, content=b"x", text="suspended")
    with patch.object(main.requests, "get", return_value=r) as g:
        main._upstash_probe(now=500.0)
    assert g.call_count == 1


def test_health_exposes_upstash_status():
    h = asyncio.run(main.health())
    for k in ("upstash_ok", "upstash_error", "upstash_checked_at", "upstash_last_ok_at"):
        assert k in h


def test_view4_polls_health_and_never_hides_a_failed_stop_check():
    src = (Path(__file__).resolve().parent.parent / "static" / "trade-view4.html").read_text()
    assert 'getJSON("/health")' in src and "Render unreachable since" in src and "Upstash DOWN" in src
    i = src.index("async function pollProtection")
    assert "catch (e) {}" not in src[i:src.index("async function pollPositions")]


def test_tabs_shell_shows_system_health_for_every_view():
    src = (Path(__file__).resolve().parent.parent / "static" / "trade-view-tabs.html").read_text()
    assert 'fetch("/health"' in src and "Render unreachable since" in src and "Upstash down" in src


def test_health_is_async_and_reports_threadpool():
    """B-1359: /health must not queue behind a full worker pool (23-Oct: it hung while a 404 answered in 1 s)."""
    import inspect
    import main
    from fastapi.testclient import TestClient
    assert inspect.iscoroutinefunction(main.health)
    with TestClient(main.app) as c:
        h = c.get("/health").json()
    assert h["threadpool_total"] and h["threadpool_used"] is not None


def test_watchdog_alarms_on_full_threadpool():
    import time
    from unittest.mock import patch
    import main
    with patch.dict(main._WATCHDOG_STATE, {"threadpool_used": 40, "threadpool_total": 40}), \
            patch.object(main, "_loop_heartbeat_ts", time.time()), patch.object(main, "_busy_thread_stacks", return_value=[]):
        info = main._watchdog_check(rss_mb=100)
    assert info and info["threadpool"] == "40/40"


def test_views_flag_stuck_workers():
    for f in ("static/trade-view-tabs.html", "static/trade-view4.html"):
        assert "threadpool_used >= h.threadpool_total" in open(f).read()


def test_view_polls_are_single_flight_with_timeout():
    """B-1359: polls every 2-5 s must not stack up behind a slow endpoint and fill the bot's worker pool."""
    v4 = open("static/trade-view4.html").read()
    assert "inflight[k]" in v4 and "ac.abort()" in v4
    tabs = open("static/trade-view-tabs.html").read()
    assert "if (busy) return" in tabs and "AbortSignal.timeout" in tabs
