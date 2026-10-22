"""B-1342: daily Upstash budget guard. Today's usage survives restarts, non-critical writers back off as the day's
budget fills and outside market hours, real-money tables are never throttled, and status is checkable daily."""
import main


class _Store:
    def __init__(self):
        self.kv, self.sets = {}, []

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value):
        self.sets.append((key, len(value)))
        self.kv[key] = value


def _wire(monkeypatch, store):
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", store.get)
    monkeypatch.setattr(main, "_upstash_set", store.set)


def _fill(monkeypatch, nbytes=0, ops=0):
    day = main.ist_now().strftime("%Y-%m-%d")
    monkeypatch.setattr(main, "_upstash_usage", {"x": {"get_ops": ops, "get_bytes": 0, "set_ops": 0, "set_bytes": nbytes}})
    monkeypatch.setattr(main, "_upstash_usage_day", day)
    monkeypatch.setattr(main, "_upstash_usage_base", {})
    monkeypatch.setattr(main, "_upstash_usage_base_day", day)


def test_levels_and_intervals_follow_budget_and_market_hours(monkeypatch):
    monkeypatch.setattr(main, "_upstash_in_market_hours", lambda: True)
    _fill(monkeypatch, nbytes=10)
    assert main._upstash_budget_level() == 0 and main._upstash_noncritical_interval(300) == 300
    _fill(monkeypatch, nbytes=int(main._UPSTASH_DAILY_BYTES_BUDGET * 0.7))
    assert main._upstash_budget_level() == 1 and main._upstash_noncritical_interval(300) == 1800
    _fill(monkeypatch, ops=int(main._UPSTASH_DAILY_OPS_BUDGET * 0.95))  # commands count too, not just bytes
    assert main._upstash_budget_level() == 2 and main._upstash_noncritical_interval(300) is None
    _fill(monkeypatch, nbytes=10)
    monkeypatch.setattr(main, "_upstash_in_market_hours", lambda: False)
    assert main._upstash_noncritical_interval(300) == 1800


def test_market_hours_window(monkeypatch):
    dt = main.dt.datetime
    for when, expect in [(dt(2026, 10, 23, 9, 30), True), (dt(2026, 10, 23, 15, 45), True),
                         (dt(2026, 10, 23, 8, 59), False), (dt(2026, 10, 23, 20, 0), False),
                         (dt(2026, 10, 24, 11, 0), False)]:  # Saturday
        monkeypatch.setattr(main, "ist_now", lambda w=when: w)
        assert main._upstash_in_market_hours() is expect


def test_todays_usage_survives_a_restart(monkeypatch):
    store = _Store()
    _wire(monkeypatch, store)
    day = main.ist_now().strftime("%Y-%m-%d")
    store.kv[main._UPSTASH_USAGE_KEY] = main.json.dumps(
        {"day": day, "families": {"fam": {"get_ops": 3, "get_bytes": 1000, "set_ops": 2, "set_bytes": 5000}}})
    monkeypatch.setattr(main, "_upstash_usage", {})
    monkeypatch.setattr(main, "_upstash_usage_day", day)
    monkeypatch.setattr(main, "_upstash_usage_base", {})
    monkeypatch.setattr(main, "_upstash_usage_base_day", "")
    main._upstash_meter("fam", 400, "set")  # this process
    main._upstash_usage_persist(force=True)
    out = main.upstash_usage()
    assert out["families"]["fam"]["set_bytes"] == 5400 and out["restored_from_earlier_processes"] is True
    saved = main.json.loads(store.kv[main._UPSTASH_USAGE_KEY])
    assert saved["day"] == day and saved["families"]["fam"]["set_bytes"] == 5400
    # a stale (yesterday) record is not added to today
    store.kv[main._UPSTASH_USAGE_KEY] = main.json.dumps({"day": "2000-01-01", "families": {"fam": {"set_bytes": 9}}})
    monkeypatch.setattr(main, "_upstash_usage_base_day", "")
    main._upstash_usage_persist(force=True)
    assert main.upstash_usage()["families"]["fam"]["set_bytes"] == 400


def test_critical_pauses_noncritical_writers_but_real_money_tables_still_push(monkeypatch):
    store = _Store()
    _wire(monkeypatch, store)
    monkeypatch.setattr(main, "_upstash_budget_level", lambda: 2)
    calls = []
    monkeypatch.setattr(main, "_sync_check_counts_external", lambda d, c: calls.append(1))
    monkeypatch.setattr(main, "_check_counts_last_sync", 0.0)
    monkeypatch.setattr(main, "_check_counts_last_digest", None)
    main._maybe_sync_check_counts_external()
    assert calls == []
    monkeypatch.setattr(main, "_fo_candles_last_sync", 0.0)
    monkeypatch.setattr(main, "sync_fo_option_candles_external", lambda: calls.append(2) or 1)
    assert main._maybe_sync_fo_option_candles_external() == 0 and calls == []
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set(main._GENERIC_MIRROR_UPSTASH_TABLES))
    monkeypatch.setattr(main, "_generic_mirror_last_hash", {})
    monkeypatch.setattr(main, "_generic_mirror_last_push_ts", {})
    main.sync_generic_tables_external()
    pushed = {k.split(":")[2] for k, _ in store.sets}
    assert not pushed & set(main._GENERIC_MIRROR_SLOW_TABLES)
    assert "trading_control" in pushed and "positions" in pushed


def test_endpoint_reports_status_and_daily_workflow_flags_it(monkeypatch):
    _fill(monkeypatch, nbytes=int(main._UPSTASH_DAILY_BYTES_BUDGET * 0.95))
    out = main.upstash_usage()
    assert out["status"] == "critical" and out["bytes_pct"] >= 90 and "market_hours" in out
    wf = open(".github/workflows/upstash-usage-check.yml").read()
    assert "/upstash-usage" in wf and "schedule" in wf and "exit 1" in wf
