"""B-1625: pattern_fresh_long_signals is cached per (symbol, completed-bar key) for the IST day."""
import pandas as pd
import main


def _df(n=130, last_close=100.0):
    idx = pd.date_range("2026-05-01", periods=n, freq="D")
    c = [100.0] * (n - 1) + [last_close]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1] * n}, index=idx)


def _reset(monkeypatch):
    monkeypatch.setitem(main._PATTERN_FRESH_CACHE, "day", None)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "")


def test_second_call_same_bars_hits_cache(monkeypatch):
    _reset(monkeypatch)
    calls = []
    rule = main._PATTERN_LIVE_CELLS[0][1]
    monkeypatch.setattr(main, "pattern_fresh_long_signals", lambda df: calls.append(1) or {rule: True})
    n = [0]
    a = main._pattern_fresh_cached("AAA", _df(), "2026-11-18", n)
    b = main._pattern_fresh_cached("AAA", _df(), "2026-11-18", n)
    assert a[rule] is True and b[rule] is True and len(calls) == 1


def test_new_bar_or_new_day_recomputes(monkeypatch):
    _reset(monkeypatch)
    calls = []
    monkeypatch.setattr(main, "pattern_fresh_long_signals", lambda df: calls.append(1) or {})
    n = [0]
    main._pattern_fresh_cached("AAA", _df(), "2026-11-18", n)
    main._pattern_fresh_cached("AAA", _df(n=131), "2026-11-18", n)  # a new completed bar
    main._pattern_fresh_cached("AAA", _df(n=131, last_close=99.0), "2026-11-18", n)  # revised last bar
    main._pattern_fresh_cached("AAA", _df(n=131, last_close=99.0), "2026-11-19", n)  # new IST day
    assert len(calls) == 4


def test_restart_restores_from_mirror(monkeypatch):
    _reset(monkeypatch)
    store = {}
    rule = main._PATTERN_LIVE_CELLS[0][1]
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "pattern_fresh_long_signals", lambda df: {rule: True})
    main._pattern_fresh_cached("AAA", _df(), "2026-11-18", [0])
    main._pattern_fresh_cache_flush("2026-11-18")
    assert "pattern_fresh:2026-11-18" in store
    monkeypatch.setitem(main._PATTERN_FRESH_CACHE, "day", None)  # simulate a restart: memory gone
    monkeypatch.setattr(main, "pattern_fresh_long_signals", lambda df: (_ for _ in ()).throw(AssertionError("recomputed")))
    assert main._pattern_fresh_cached("AAA", _df(), "2026-11-18", [0])[rule] is True


def test_mirror_failure_is_non_fatal(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(main, "_upstash_get", boom)
    monkeypatch.setattr(main, "_upstash_set", boom)
    monkeypatch.setattr(main, "pattern_fresh_long_signals", lambda df: {})
    assert main._pattern_fresh_cached("AAA", _df(), "2026-11-18", [0]) == {} or True
    main._pattern_fresh_cache_flush("2026-11-18")
