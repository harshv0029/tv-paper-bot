import main


def test_headroom_math():
    h = main._rss_headroom(1024.0)
    assert (h["rss_mb"], h["rss_limit_mb"], h["rss_pct"]) == (1024.0, 2048, 50.0)


def test_alarm_threshold_math():
    assert main._rss_headroom(1800.0)["rss_pct"] > main.RSS_ALARM_PCT
    assert main._rss_headroom(1000.0)["rss_pct"] < main.RSS_ALARM_PCT


def test_health_keys():
    h = main.health()
    for k in ("status", "time", "rss_mb", "rss_limit_mb", "rss_pct"):
        assert k in h
    assert h["rss_limit_mb"] == 2048


def test_current_rss_and_arena_cap_b1290():
    import main
    cur = main._current_rss_mb()
    assert cur is None or cur > 0
    assert "rss_now_mb" in main._rss_headroom(100.0)
    main._cap_malloc_arenas()  # must never raise
