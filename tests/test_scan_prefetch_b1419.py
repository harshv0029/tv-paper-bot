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
    assert "await asyncio.to_thread(_scan_equity_symbol_sync" in tick  # one worker-thread hop per symbol
    sync = src[src.index("def _scan_equity_symbol_sync("):src.index("BAR_SWEEP_SETTLE_SECONDS = 20")]
    assert "with _SCAN_DECISION_LOCK:" in sync and "await" not in sync
    assert "short_result = _timed_call(\"short_engine\", _short_signal_core," in sync and "_real_on_thread(_maybe_place_real_entry" in sync
    assert "await asyncio.sleep(_scheduler_sleep_after_tick(_tick_seconds))" in tick
    assert "await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)\n" not in tick.split("for symbol in _scan_visit")[1]


# ---- option A: 5m-bar sweep ----
import asyncio  # noqa: E402

_B = 1793260800  # an exact 5-minute epoch boundary


def test_next_bar_sweep_timing():
    assert _B % 300 == 0
    assert main._seconds_to_next_bar_sweep(_B) == 20          # boundary -> wait for the settle
    assert main._seconds_to_next_bar_sweep(_B + 10) == 10
    assert main._seconds_to_next_bar_sweep(_B + 25) == 295    # just swept -> next bar
    assert main._seconds_to_next_bar_sweep(_B + 299) == 21


def test_candidates_skip_symbols_already_scanned_this_bar(monkeypatch):
    monkeypatch.setattr(main, "WATCHLIST", [{"symbol": "A.NS"}, {"symbol": "B.NS"}, {"symbol": "GC=F"}])
    monkeypatch.setattr(main, "_SCAN_LAST_DONE", {"A.NS": _B + 5, "B.NS": _B - 5})
    assert main._bar_sweep_candidates(_B) == ["B.NS"]


def test_bar_sweep_does_nothing_when_market_closed(monkeypatch):
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: False)
    called = []
    monkeypatch.setattr(main, "_scan_equity_symbol_sync", lambda *a, **k: called.append(a))
    st = asyncio.run(main._bar_sweep_once(now=_B + 20))
    assert st["status"] == "market_closed" and not called


def test_bar_sweep_scans_every_unscanned_equity_once(monkeypatch):
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(main, "is_trading_enabled", lambda c: True)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 10000.0)
    monkeypatch.setattr(main, "_prefetch_tick_ohlc", lambda syms: {"symbols": len(syms)})
    monkeypatch.setattr(main, "WATCHLIST", [{"symbol": s} for s in ("A.NS", "B.NS", "C.NS", "^NSEI")])
    monkeypatch.setattr(main, "_SCAN_LAST_DONE", {"B.NS": _B + 1})
    import time as _t
    monkeypatch.setattr(main.time, "time", lambda: _B + 20)
    seen = []

    def fake_scan(sym, cfg, cap, risk, rr, hold):
        seen.append((sym, cfg["symbol"], cap))
        main._SCAN_LAST_DONE[sym] = _B + 30
    monkeypatch.setattr(main, "_scan_equity_symbol_sync", fake_scan)
    st = asyncio.run(main._bar_sweep_once(now=_B + 20))
    assert [s for s, _, _ in seen] == ["A.NS", "C.NS"] and all(c == 10000.0 for _, _, c in seen)
    assert st["status"] == "complete" and st["candidates"] == 2 and st["covered"] == 2
    assert st["bar_close_ist"].endswith("IST")


def test_bar_sweep_task_is_started_and_reported():
    src = open(main.__file__).read()
    assert "asyncio.create_task(_bar_sweep_loop())" in src
    assert '"bar_sweep": _BAR_SWEEP_STATS' in src


def test_scan_decision_lock_serialises_scanners(monkeypatch):
    """Two scanners (tick + bar sweep) never run a symbol's decision code at the same time."""
    active, peak, lock = [0], [0], threading.Lock()

    def fake_core(**kw):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        raise RuntimeError("stop after the long engine")
    monkeypatch.setattr(main, "_auto_signal_core", fake_core)
    cfg = {**main.NSE_STOCK_DEFAULT_PARAMS, "symbol": "X.NS"}
    ts = [threading.Thread(target=main._scan_equity_symbol_sync, args=("X.NS", cfg, 1.0, 2.0, 3.0, 0))
          for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert peak[0] == 1
    assert main._scheduler_last_results["X.NS"]["status"] == "error"


def test_b1422_total_yahoo_downloads_capped():
    data_fetch._DATA_CACHE.clear()
    active, peak, lock = [0], [0], threading.Lock()

    def slow_download(sym, period, interval, progress):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.03)
        with lock:
            active[0] -= 1
        return _df()
    with patch.object(data_fetch.yf, "download", side_effect=slow_download):
        ts = [threading.Thread(target=data_fetch.fetch_ohlc, args=(f"Z{i}.NS", "5d", "5m")) for i in range(16)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert 1 < peak[0] <= data_fetch._YF_MAX_CONCURRENT
    data_fetch._DATA_CACHE.clear()


def test_sweep_yields_to_a_waiting_tick(monkeypatch):
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(main, "is_trading_enabled", lambda c: True)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 1.0)
    monkeypatch.setattr(main, "_prefetch_tick_ohlc", lambda syms: {})
    monkeypatch.setattr(main, "WATCHLIST", [{"symbol": "A.NS"}])
    monkeypatch.setattr(main, "_SCAN_LAST_DONE", {})
    clock = {"t": _B + 20.0}
    monkeypatch.setattr(main.time, "time", lambda: clock["t"])
    main._TICK_WANTS_SCAN["n"] = 1
    scanned = []

    async def fake_sleep(s):
        clock["t"] += s
        if clock["t"] > _B + 22:
            main._TICK_WANTS_SCAN["n"] = 0  # tick finished its symbol
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_scan_equity_symbol_sync", lambda sym, *a: scanned.append((sym, clock["t"])))
    try:
        asyncio.run(main._bar_sweep_once(now=_B + 20))
    finally:
        main._TICK_WANTS_SCAN["n"] = 0
    assert scanned and scanned[0][1] > _B + 22  # waited for the tick first


def test_tick_hands_flat_nse_to_the_sweep_in_session(monkeypatch):
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "is_nse_trading_day", lambda *a, **k: True)
    monkeypatch.setitem(main._BAR_SWEEP_STATS, "last", None)
    assert main._bar_sweep_owns_flat_nse()
    monkeypatch.setitem(main._BAR_SWEEP_STATS, "last", {"status": "error"})
    assert not main._bar_sweep_owns_flat_nse()  # a failing sweep gives the round-robin back to the tick
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: False)
    monkeypatch.setitem(main._BAR_SWEEP_STATS, "last", None)
    assert not main._bar_sweep_owns_flat_nse()


def test_section_timing_recorded():
    main._SCAN_SECTION_STATS.clear()
    main._timed_call("x", lambda: sum(range(1000)))
    summ = main._scan_sections_summary()
    assert summ["x"]["n"] == 1 and summ["x"]["avg_wall_s"] >= 0
    main._SCAN_SECTION_STATS.clear()
