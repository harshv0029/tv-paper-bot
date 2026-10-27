import threading
import time

import sentiment_signals as ss


def _reset():
    ss._cache.update({"fetched_at": 0.0, "date": None, "data": None})


def test_cold_cache_returns_immediately_and_refreshes_in_background(monkeypatch):
    _reset()
    gate = threading.Event()

    def slow_fetch(date_str):
        gate.wait(5)
        return "| Symbol | Sentiment | Why |\n|---|---|---|\n| NIFTY | Bearish | x |\n"
    monkeypatch.setattr(ss, "_fetch_file", slow_fetch)
    t0 = time.time()
    data = ss.get_latest_sentiment("2026-10-27")
    assert time.time() - t0 < 1.0
    assert data["signals"] == {}  # fail open while the refresh runs
    gate.set()
    for _ in range(50):
        if ss._cache["data"]:
            break
        time.sleep(0.05)
    assert ss._cache["data"]["as_of_date"] == "2026-10-27"


def test_stale_cache_served_while_refreshing(monkeypatch):
    stale = {"as_of_date": "2026-10-26", "signals": {"NIFTY": "Bullish"}, "source": None}
    ss._cache.update({"fetched_at": time.time() - 10_000, "date": "2026-10-27", "data": stale})
    monkeypatch.setattr(ss, "_fetch_file", lambda d: (time.sleep(2), None)[1])
    t0 = time.time()
    assert ss.get_latest_sentiment("2026-10-27") is stale
    assert time.time() - t0 < 1.0


def test_wait_true_fetches_synchronously(monkeypatch):
    _reset()
    monkeypatch.setattr(ss, "_fetch_file", lambda d: None)
    assert ss.get_latest_sentiment("2026-10-27", wait=True)["signals"] == {}
    assert ss._cache["date"] == "2026-10-27"
