import main


def test_headroom_math():
    h = main._rss_headroom(1024.0)
    assert h == {"rss_mb": 1024.0, "rss_limit_mb": 2048, "rss_pct": 50.0}


def test_alarm_threshold_math():
    assert main._rss_headroom(1800.0)["rss_pct"] > main.RSS_ALARM_PCT
    assert main._rss_headroom(1000.0)["rss_pct"] < main.RSS_ALARM_PCT


def test_health_keys():
    h = main.health()
    for k in ("status", "time", "rss_mb", "rss_limit_mb", "rss_pct"):
        assert k in h
    assert h["rss_limit_mb"] == 2048
