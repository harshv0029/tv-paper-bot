"""B-1341: the free Upstash DB was suspended for its 10 GB/month bandwidth cap. Pushes must be compressed,
skipped when unchanged, throttled, and metered."""
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


def test_symbol_scans_compressed_skipped_when_unchanged_and_restorable(monkeypatch):
    store = _Store()
    _wire(monkeypatch, store)
    today = main.ist_now().strftime("%Y-%m-%d")
    tags = {f"family_{i}__variant__long__1d__atr6_h20__v1" for i in range(300)}
    monkeypatch.setattr(main, "_symbol_strategy_scans", {f"SYM{j}.NS": set(tags) for j in range(200)})
    monkeypatch.setattr(main, "_symbol_strategy_scans_day", today)
    monkeypatch.setattr(main, "_symbol_scans_last_digest", None)
    main._symbol_scans_push_now()
    main._symbol_scans_push_now()  # unchanged: no second upload
    assert len(store.sets) == 1
    raw_size = 200 * sum(len(t) + 3 for t in tags)
    assert store.sets[0][1] < raw_size / 20  # was ~2.8 MB uncompressed every 60 s
    main._symbol_strategy_scans.clear()
    assert main._symbol_scans_hydrate_now() is True
    assert main._symbol_strategy_scans["SYM7.NS"] == tags


def test_symbol_scans_hydrate_still_reads_the_old_plain_json_blob(monkeypatch):
    store = _Store()
    _wire(monkeypatch, store)
    today = main.ist_now().strftime("%Y-%m-%d")
    store.kv[main._SYMBOL_SCANS_REDIS_KEY] = main.json.dumps({"day": today, "scans": {"TCS.NS": ["a", "b"]}})
    monkeypatch.setattr(main, "_symbol_strategy_scans", {})
    assert main._symbol_scans_hydrate_now() is True
    assert main._symbol_strategy_scans["TCS.NS"] == {"a", "b"}


def test_check_counts_sync_is_throttled_and_skips_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_sync_check_counts_external", lambda d, c: calls.append(dict(c)))
    monkeypatch.setattr(main, "_scheduler_check_counts_day", "2026-10-23")
    monkeypatch.setattr(main, "_scheduler_check_counts", {"TCS.NS": 1})
    monkeypatch.setattr(main, "_check_counts_last_sync", 0.0)
    monkeypatch.setattr(main, "_check_counts_last_digest", None)
    main._maybe_sync_check_counts_external()
    main._scheduler_check_counts["TCS.NS"] = 2
    main._maybe_sync_check_counts_external()  # inside the 300 s window
    assert len(calls) == 1
    monkeypatch.setattr(main, "_check_counts_last_sync", 0.0)
    main._maybe_sync_check_counts_external()
    assert len(calls) == 2
    monkeypatch.setattr(main, "_check_counts_last_sync", 0.0)
    main._maybe_sync_check_counts_external()  # unchanged: no upload
    assert len(calls) == 2


def test_slow_tables_wait_on_the_tick_path_but_critical_tables_push_on_change(monkeypatch):
    store = _Store()
    _wire(monkeypatch, store)
    monkeypatch.setattr(main, "_generic_mirror_hydrated", set(main._GENERIC_MIRROR_UPSTASH_TABLES))
    monkeypatch.setattr(main, "_generic_mirror_last_hash", {})
    monkeypatch.setattr(main, "_generic_mirror_last_push_ts", {t: main.time.time() for t in main._GENERIC_MIRROR_SLOW_TABLES})
    main.sync_generic_tables_external()
    pushed = {k.split(":")[2] for k, _ in store.sets}
    assert not pushed & set(main._GENERIC_MIRROR_SLOW_TABLES)
    assert "trading_control" in pushed and "positions" in pushed
    store.sets.clear()
    main.sync_generic_tables_external(only=("swing_ltp_peak",))  # explicit call is immediate
    assert {k.split(":")[2] for k, _ in store.sets} == {"swing_ltp_peak"}


def test_usage_meter_groups_chunks_and_days(monkeypatch):
    monkeypatch.setattr(main, "_upstash_usage", {})
    main._upstash_meter("tv_paper_bot:tbl:trades:v1:c0", 100, "set")
    main._upstash_meter("tv_paper_bot:tbl:trades:v1:c1", 50, "set")
    main._upstash_meter("fo:2026-10-22:meta", 7, "get")
    out = main.upstash_usage()
    assert out["families"]["tv_paper_bot:tbl:trades:v1"]["set_bytes"] == 150
    assert out["total_bytes"] == 157
