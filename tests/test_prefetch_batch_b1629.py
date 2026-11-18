"""B-1629: the tick/bar-sweep prefetch submits in bounded batches and trims the native heap between them."""
import threading
import time

import main


def _run(monkeypatch, n_syms, batch, fetch=None, timeout=None):
    inflight = {"now": 0, "max": 0}
    lock = threading.Lock()
    trims = []

    def fake(sym, period, iv):
        with lock:
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
        try:
            if fetch:
                return fetch(sym, period, iv)
            return time.time(), {"s": sym, "iv": iv}
        finally:
            with lock:
                inflight["now"] -= 1

    monkeypatch.setattr(main, "_prefetch_one_frame", fake)
    monkeypatch.setattr(main, "SCAN_PREFETCH_BATCH_KEYS", batch)
    monkeypatch.setattr(main, "_malloc_trim_only", lambda: trims.append(1) or True)
    col = {}
    out = main._prefetch_tick_ohlc_impl([f"S{i}" for i in range(n_syms)], intervals=["5m", "15m"], workers=4,
                                        collect=col, timeout=timeout)
    return out, col, trims


def test_all_keys_fetched_in_batches(monkeypatch):
    out, col, trims = _run(monkeypatch, 25, 10)
    assert out["ok"] == 50 and out["failed"] == 0
    assert out["batches"] == 5 and len(trims) == 5
    assert len(col) == 50


def test_small_request_single_batch_no_trim(monkeypatch):
    out, col, trims = _run(monkeypatch, 3, 48)
    assert out["ok"] == 6 and out["batches"] == 1 and trims == []


def test_failures_counted_and_rest_continue(monkeypatch):
    def fetch(sym, period, iv):
        if sym == "S1":
            raise RuntimeError("boom")
        return time.time(), {}
    out, col, _ = _run(monkeypatch, 10, 4, fetch=fetch)
    assert out["ok"] == 18 and out["failed"] == 2


def test_timeout_counts_unsubmitted_keys(monkeypatch):
    def fetch(sym, period, iv):
        time.sleep(0.2)
        return time.time(), {}
    out, col, _ = _run(monkeypatch, 20, 4, fetch=fetch, timeout=0.3)
    assert out["ok"] + out["failed"] == 40
    assert out["failed"] > 0
