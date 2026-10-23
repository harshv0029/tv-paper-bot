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


def test_health_exposes_upstash_status():
    h = main.health()
    for k in ("upstash_ok", "upstash_error", "upstash_checked_at", "upstash_last_ok_at"):
        assert k in h


def test_view4_polls_health_and_never_hides_a_failed_stop_check():
    src = (Path(__file__).resolve().parent.parent / "static" / "trade-view4.html").read_text()
    assert 'getJSON("/health")' in src and "Render unreachable since" in src and "Upstash DOWN" in src
    i = src.index("async function pollProtection")
    assert "catch (e) {}" not in src[i:src.index("async function pollPositions")]
