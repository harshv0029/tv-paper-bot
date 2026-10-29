"""B-1419: parallel bar prefetch per scheduler tick, thread-safe fetch cache, short scan off the loop."""
import threading
import time
from unittest.mock import patch

import pandas as pd

import data_fetch
import main


def _df():
    return pd.DataFrame({"Datetime": pd.date_range("2026-10-29 09:15", periods=3, freq="5min"),
                         "Open": [1.0, 2, 3], "High": [1.0, 2, 3], "Low": [1.0, 2, 3], "Close": [1.0, 2, 3]})


def test_prefetch_fetches_each_symbol_once_in_parallel():
    seen, active, peak, lock = [], [0], [0], threading.Lock()

    def fake(sym, period, interval):
        with lock:
            seen.append((sym, period, interval))
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        if sym == "BAD.NS":
            raise RuntimeError("no data")
        return _df()

    with patch("main.fetch_ohlc", side_effect=fake):
        out = main._prefetch_tick_ohlc(["A.NS", "B.NS", "A.NS", "BAD.NS", "C.NS"], workers=4)
    assert sorted(s for s, _, _ in seen) == ["A.NS", "B.NS", "BAD.NS", "C.NS"]
    assert all(p == "5d" and i == "5m" for _, p, i in seen)
    assert out["symbols"] == 4 and out["ok"] == 3 and out["failed"] == 1
    assert peak[0] > 1  # really ran concurrently


def test_prefetch_empty_is_noop():
    assert main._prefetch_tick_ohlc([])["symbols"] == 0


def test_fetch_cache_survives_concurrent_threads():
    data_fetch._DATA_CACHE.clear()
    calls = []

    def fake_download(sym, period, interval, progress):
        calls.append(sym)
        time.sleep(0.01)
        return _df()

    errors = []

    def worker(i):
        try:
            for j in range(20):
                data_fetch.fetch_ohlc(f"S{(i * 7 + j) % 30}.NS", "5d", "5m")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    with patch.object(data_fetch.yf, "download", side_effect=fake_download), \
         patch.object(data_fetch, "_MAX_CACHE_ENTRIES", 10):
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert not errors
    assert len(data_fetch._DATA_CACHE) <= 10 + 8  # cap holds (one in-flight insert per thread at most)
    data_fetch._DATA_CACHE.clear()


def test_sleep_after_tick_only_tops_up_the_interval():
    assert main._scheduler_sleep_after_tick(0) == main.SCHEDULER_INTERVAL_SECONDS
    assert main._scheduler_sleep_after_tick(10) == main.SCHEDULER_INTERVAL_SECONDS - 10
    assert main._scheduler_sleep_after_tick(120) == 1.0


def test_tick_timing_is_recorded_and_summarised():
    main._SCHEDULER_TICK_TIMING.update({"last": None, "recent": []})
    for k in range(25):
        main._record_tick_timing({"tick_seconds": float(k)})
    summ = main._tick_timing_summary()
    assert summ["n_recent"] == main._SCHEDULER_TICK_TIMING_KEEP
    assert summ["last"]["tick_seconds"] == 24.0
    main._SCHEDULER_TICK_TIMING.update({"last": None, "recent": []})


def test_tick_wiring_source():
    src = open(main.__file__).read()
    tick = src[src.index("async def _scheduler_tick():"):src.index("STARTUP_HYDRATION_TIMEOUT_SECONDS = 15")]
    assert "_prefetch_tick_ohlc" in tick
    assert "await asyncio.to_thread(\n                    _short_signal_core," in tick
    assert "await asyncio.sleep(_scheduler_sleep_after_tick(_tick_seconds))" in tick
    assert "await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)\n" not in tick.split("for symbol in _scan_visit")[1]
