"""B-1447: tick prefetch and the open-positions price fetch reuse one long-lived thread pool, so yfinance's
curl_cffi per-thread Curl handles are not rebuilt on every 30 s tick / dashboard poll."""
import threading

import pandas as pd

import main


def _fake_fetch(names):
    def f(symbol, period, interval):
        names.add(threading.current_thread().name)
        return pd.DataFrame({"Close": [1.0]})
    return f


def test_prefetch_reuses_same_pool_and_threads(monkeypatch):
    names = set()
    monkeypatch.setattr(main, "fetch_ohlc", _fake_fetch(names))
    main._prefetch_tick_ohlc_impl(["A.NS", "B.NS", "C.NS"], workers=3)
    pool = main._prefetch_pool(3)
    main._prefetch_tick_ohlc_impl(["A.NS", "B.NS", "C.NS"], workers=3)
    assert main._prefetch_pool(3) is pool
    assert len(pool._threads) <= 3  # never more than one set of worker threads for the process
    assert names <= {t.name for t in pool._threads}
    assert all(n.startswith("scan-prefetch") for n in names)


def test_pool_size_does_not_follow_symbol_count(monkeypatch):
    monkeypatch.setattr(main, "fetch_ohlc", _fake_fetch(set()))
    before = set(main._PREFETCH_POOLS)
    main._prefetch_tick_ohlc_impl(["A.NS"])
    main._prefetch_tick_ohlc_impl(["A.NS", "B.NS"])
    assert set(main._PREFETCH_POOLS) - before <= {("scan-prefetch", main.SCAN_PREFETCH_WORKERS)}


def test_open_positions_prices_uses_persistent_pool(monkeypatch):
    monkeypatch.setattr(main, "fetch_ohlc", lambda s, p, i: pd.DataFrame({"Close": [10.0]}))
    out1 = main._open_positions_prices(["X.NS"], {}, budget_s=5)
    pool = main._prefetch_pool(8, "op-price")
    out2 = main._open_positions_prices(["Y.NS"], {}, budget_s=5)
    assert out1 == {"X.NS": 10.0} and out2 == {"Y.NS": 10.0}
    assert main._prefetch_pool(8, "op-price") is pool
