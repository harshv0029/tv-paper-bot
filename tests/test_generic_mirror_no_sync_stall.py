"""B-1306/B-1311: with Upstash failing, a mirror push must not re-run the whole restore synchronously on every call
(live 2026-10-22 09:25 IST: the reconcile sat 3+ min in _upstash_get)."""
import requests

import main


def test_push_retries_only_its_own_tables_and_is_throttled(monkeypatch):
    calls = []

    def boom(key):
        calls.append(key)
        raise requests.exceptions.ConnectionError("upstash down")

    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", boom)
    monkeypatch.setattr(main, "_upstash_set", lambda *a, **k: None)
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set())
    monkeypatch.setattr(main, "_generic_hydrate_last_try", {})
    # real_order_events is git-tier, not an Upstash table: logging an order event must not touch the Upstash restore
    # at all (this is the call _log_real_order_event makes on every real order step).
    main.sync_generic_tables_external(only=("real_order_events",))
    assert calls == []
    main.sync_generic_tables_external(only=("trades",))
    assert calls and all(":trades:" in k for k in calls)
    assert len(calls) == 1  # pass stops at the first network failure
    main.sync_generic_tables_external(only=("trades",))
    assert len(calls) == 1  # throttled: no second synchronous restore within the retry window


def test_full_restore_pass_stops_at_first_network_failure(monkeypatch):
    calls = []

    def boom(key):
        calls.append(key)
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", boom)
    monkeypatch.setattr(main, "hydrate_git_tier_tables", lambda: 0)
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set())
    main.hydrate_generic_tables_from_external()
    assert len(calls) == 1
