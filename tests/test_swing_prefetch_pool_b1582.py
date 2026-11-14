"""B-1582: the swing pass's 2y daily prefetch reuses one persistent 8-thread pool across passes (no fresh pool, and
so no fresh curl_cffi handles, every 15-min pass), keeps input order and the B-1391 single retry, and the memory
pressure clear empties the data cache under its lock."""
import threading

import pandas as pd

import data_fetch
import main


def test_swing_prefetch_reuses_one_pool_and_keeps_order(monkeypatch):
    names = set()

    def fake(symbol, period, interval):
        names.add(threading.current_thread().name)
        assert (period, interval) == ("2y", "1d")
        return pd.DataFrame({"Close": [1.0]})

    monkeypatch.setattr(main, "fetch_ohlc", fake)
    syms = [f"S{i}.NS" for i in range(20)]
    out1 = main._swing_prefetch_daily(syms)
    pool = main._prefetch_pool(main.SWING_PREFETCH_WORKERS, "swing-prefetch")
    out2 = main._swing_prefetch_daily(syms)
    assert list(out1) == syms and list(out2) == syms
    assert all(err is None and len(df) == 1 for df, err in out1.values())
    assert main._prefetch_pool(main.SWING_PREFETCH_WORKERS, "swing-prefetch") is pool
    assert len(pool._threads) <= main.SWING_PREFETCH_WORKERS
    assert names and all(n.startswith("swing-prefetch") for n in names)


def test_swing_prefetch_retries_once_then_reports_error(monkeypatch):
    calls = {}

    def fake(symbol, period, interval):
        calls[symbol] = calls.get(symbol, 0) + 1
        if symbol == "BAD.NS" or calls[symbol] == 1:
            raise RuntimeError("throttled")
        return pd.DataFrame({"Close": [2.0]})

    monkeypatch.setattr(main, "fetch_ohlc", fake)
    monkeypatch.setattr(main, "SWING_FETCH_RETRY_PAUSE_S", 0.0)
    out = main._swing_prefetch_daily(["OK.NS", "BAD.NS"])
    assert out["OK.NS"][1] is None and float(out["OK.NS"][0]["Close"].iloc[0]) == 2.0
    assert out["BAD.NS"][0] is None and isinstance(out["BAD.NS"][1], RuntimeError)
    assert calls == {"OK.NS": 2, "BAD.NS": 2}


def test_swing_pass_has_no_per_pass_executor():
    import inspect
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "ThreadPoolExecutor" not in src and "_swing_prefetch_daily(" in src


def test_pressure_clear_empties_data_cache(monkeypatch):
    monkeypatch.setattr(main, "_trim_native_heap", lambda: True)
    monkeypatch.setitem(main._MEMORY_STATE, "last_trim_ts", None)
    with data_fetch._CACHE_LOCK:
        data_fetch._DATA_CACHE[("X.NS", "5d", "5m")] = (0.0, pd.DataFrame({"Close": [1.0]}))
    out = main._memory_pressure_check(now_mb=main.RSS_LIMIT_MB * 0.9, trim=True)
    assert out["memory_level"] == "alarm"
    assert len(data_fetch._DATA_CACHE) == 0
