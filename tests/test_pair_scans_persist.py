import main


def test_roundtrip_and_same_day_only(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "y")
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    today = main.ist_now().strftime("%Y-%m-%d")
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""
    for _ in range(3):
        main._record_pair_scan("tagA", "AAA.NS", today)
    main._record_pair_scan("tagB", "BBB.NS", today)
    main._pair_scans_push_now()
    # simulated restart: memory wiped, then one fresh scan before hydration finishes
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""
    main._record_pair_scan("tagA", "AAA.NS", today)
    assert main._pair_scans_hydrate_now() is True
    assert main._pair_scan_stats[("tagA", "AAA.NS")][0] == 4  # 3 restored + 1 new
    assert main._pair_scan_stats[("tagB", "BBB.NS")][0] == 1


def test_yesterday_blob_is_ignored(monkeypatch):
    store = {main._PAIR_SCANS_REDIS_KEY: main._pair_scans_encode("2000-01-01", {("t", "S"): [9, None]})}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "y")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""
    assert main._pair_scans_hydrate_now() is True
    assert ("t", "S") not in main._pair_scan_stats
