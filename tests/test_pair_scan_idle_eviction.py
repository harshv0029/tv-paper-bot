"""B-1351: idle (tag, symbol) pairs drop their timestamp deque; counts and in-window readings are unchanged."""
import collections

import main


def _reset():
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""
    main._pair_scan_last_sweep = 0.0


def test_idle_pair_deque_freed_count_kept(monkeypatch):
    _reset()
    t = [1_000_000.0]
    monkeypatch.setattr(main.time, "time", lambda: t[0])
    main._record_pair_scan("old", "A.NS", "2026-10-26")
    main._record_pair_scan("hot", "B.NS", "2026-10-26")
    t[0] += main._PAIR_SCAN_WINDOW_SEC + 10
    main._record_pair_scan("hot", "B.NS", "2026-10-26")  # triggers the sweep (last sweep > 300 s ago)
    old, hot = main._pair_scan_stats[("old", "A.NS")], main._pair_scan_stats[("hot", "B.NS")]
    assert old[0] == 1 and old[1] == ()  # count kept, deque freed
    assert hot[0] == 2 and isinstance(hot[1], collections.deque) and len(hot[1]) == 1
    # an evicted pair rebuilds its deque on the next scan
    main._record_pair_scan("old", "A.NS", "2026-10-26")
    assert old[0] == 2 and isinstance(old[1], collections.deque) and list(old[1]) == [t[0]]


def test_sweep_keeps_in_window_pairs():
    _reset()
    now = 2_000_000.0
    main._pair_scan_stats[("a", "X")] = [3, collections.deque([now - 100], maxlen=main._PAIR_SCAN_RECENT_MAX)]
    main._pair_scan_stats[("b", "Y")] = [1, collections.deque([now - 4000], maxlen=main._PAIR_SCAN_RECENT_MAX)]
    main._pair_scan_stats[("c", "Z")] = [1, ()]
    assert main._pair_scan_drop_idle(now) == 1
    assert list(main._pair_scan_stats[("a", "X")][1]) == [now - 100]
    assert main._pair_scan_stats[("b", "Y")][1] == ()


def test_algo_live_flow_tolerates_freed_pairs():
    _reset()
    main._pair_scan_stats[("t", "S")] = [1, ()]
    from fastapi.testclient import TestClient
    r = TestClient(main.app).get("/algo-live-flow")
    assert r.status_code == 200
