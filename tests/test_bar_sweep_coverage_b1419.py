"""B-1419 (live 30-Oct 12:04 IST: 5m-bar sweep ran_out_of_bar, 71 of 187 scanned).

The sweep prefetched ~200 symbols x 2 bar sizes into data_fetch's shared cache, capped at 400 entries with
oldest-first eviction, so the frames were evicted before the scan reached them and every symbol re-downloaded from
Yahoo inline. The sweep now pins its prefetched frames for its own scan."""
import asyncio
import time
from unittest.mock import patch

import pandas as pd

import data_fetch
import main

N_SYMBOLS = 210  # 210 x 2 bar sizes + reference index = 422 frames > the 400-entry cache cap


def _frame():
    idx = pd.date_range("2026-10-30 09:15", periods=5, freq="5min", name="Datetime")
    return pd.DataFrame({"Open": [1.0] * 5, "High": [1.0] * 5, "Low": [1.0] * 5, "Close": [1.0] * 5,
                         "Volume": [1.0] * 5}, index=idx)


def _run_sweep(other_fetches_during_scan: int = 0):
    syms = [f"SW{i:03d}.NS" for i in range(N_SYMBOLS)]
    downloads = {"prefetch": 0, "scan": 0}
    phase = {"name": "prefetch"}
    scanned = []

    def fake_download(sym, period=None, interval=None, progress=False, threads=False, **kw):
        assert threads is False
        downloads[phase["name"]] += 1
        return _frame()

    def fake_symbol_scan(sym, cfg, *a):
        if phase["name"] == "prefetch":
            phase["name"] = "scan"
            # unrelated callers (tick, swing, F&O) keep filling the shared cache meanwhile
            for j in range(other_fetches_during_scan):
                data_fetch.fetch_ohlc(f"OTHER{j}.NS", "2y", "1d")
        # what _auto_signal_core / _short_signal_core fetch per symbol (cache keys of _scan_prefetch_intervals)
        for iv in main._scan_prefetch_intervals():
            main.fetch_ohlc(sym, "5d", iv)
        main._SCAN_LAST_DONE[sym] = time.time()
        scanned.append(sym)

    watch = [{"symbol": s} for s in syms]
    data_fetch._DATA_CACHE.clear()
    with patch.object(data_fetch.yf, "download", side_effect=fake_download), \
         patch.object(main, "WATCHLIST", watch), \
         patch.object(main, "BAR_SWEEP_BAR_SECONDS", 10 ** 9), \
         patch.object(main, "is_nse_trading_day", return_value=True), \
         patch.object(main, "_nse_equity_market_open_now", return_value=True), \
         patch.object(main, "is_trading_enabled", return_value=True), \
         patch.object(main, "get_runtime_setting", return_value=1.0), \
         patch.object(main, "get_scheduler_capital_inr", return_value=100000.0), \
         patch.object(main, "_scan_equity_symbol_sync", side_effect=fake_symbol_scan), \
         patch.dict(main._TICK_WANTS_SCAN, {"n": 0}), \
         patch.dict(main._SCAN_LAST_DONE, {}, clear=True):
        stats = asyncio.run(main._bar_sweep_once(now=time.time()))
    data_fetch._DATA_CACHE.clear()
    return stats, downloads, scanned


def test_sweep_scans_every_candidate_from_the_prefetch_without_redownloading():
    n_iv = len(main._scan_prefetch_intervals())
    stats, downloads, scanned = _run_sweep()
    assert stats["status"] == "complete"
    assert stats["covered"] == N_SYMBOLS and len(scanned) == N_SYMBOLS
    assert downloads["prefetch"] == (N_SYMBOLS + 1) * n_iv
    assert downloads["scan"] == 0  # old code: every evicted frame re-downloaded inline (~1.2 s each live)
    assert stats["prefetch"].get("pinned") == (N_SYMBOLS + 1) * n_iv


def test_pins_survive_other_callers_filling_the_shared_cache():
    stats, downloads, _ = _run_sweep(other_fetches_during_scan=data_fetch._MAX_CACHE_ENTRIES)
    assert stats["status"] == "complete"
    assert downloads["scan"] == data_fetch._MAX_CACHE_ENTRIES  # only the unrelated fetches themselves


def test_pins_are_scoped_to_the_sweep_and_released():
    _run_sweep()
    assert data_fetch._PINNED_FRAMES.get() is None
    pins = {("PIN.NS", "5d", "5m"): (time.time(), _frame())}
    calls = []
    tok = data_fetch._PINNED_FRAMES.set(pins)
    try:
        with patch.object(data_fetch.yf, "download", side_effect=lambda *a, **k: calls.append(a) or _frame()):
            data_fetch.fetch_ohlc("PIN.NS", "5d", "5m")
            assert calls == []  # served from the pin
            pins[("PIN.NS", "5d", "5m")] = (time.time() - data_fetch._CACHE_TTL_SECONDS - 1, _frame())
            data_fetch._DATA_CACHE.pop(("PIN.NS", "5d", "5m"), None)
            data_fetch.fetch_ohlc("PIN.NS", "5d", "5m")
            assert len(calls) == 1  # an expired pin is not served (same TTL as the shared cache)
    finally:
        data_fetch._PINNED_FRAMES.reset(tok)
        data_fetch._DATA_CACHE.clear()
