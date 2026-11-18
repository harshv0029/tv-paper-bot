"""B-1628: per-pair scan timestamps are a compact array('d'), pruned to the 1 h window and the 400 cap."""
import array

import main


def _reset():
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""


def test_record_uses_compact_array_and_prunes(monkeypatch):
    _reset()
    t = [10_000.0]
    monkeypatch.setattr(main.time, "time", lambda: t[0])
    monkeypatch.setattr(main, "_pair_scan_last_sweep", t[0])
    main._record_pair_scan("tag", "A.NS", "2026-11-18")
    rec = main._pair_scan_stats[("tag", "A.NS")]
    assert isinstance(rec[1], array.array) and list(rec[1]) == [10_000.0]
    t[0] += main._PAIR_SCAN_WINDOW_SEC + 5
    monkeypatch.setattr(main, "_pair_scan_last_sweep", t[0])
    main._record_pair_scan("tag", "A.NS", "2026-11-18")
    assert rec[0] == 2 and list(rec[1]) == [t[0]]  # the old stamp fell out of the 1 h window


def test_cap_and_reader_ops(monkeypatch):
    _reset()
    t = [50_000.0]
    monkeypatch.setattr(main.time, "time", lambda: t[0])
    monkeypatch.setattr(main, "_pair_scan_last_sweep", t[0])
    for _ in range(main._PAIR_SCAN_RECENT_MAX + 25):
        t[0] += 1
        main._record_pair_scan("tag", "B.NS", "2026-11-18")
    dq = main._pair_scan_stats[("tag", "B.NS")][1]
    assert len(dq) == main._PAIR_SCAN_RECENT_MAX and dq[-1] == t[0] and dq[0] == t[0] - main._PAIR_SCAN_RECENT_MAX + 1
    assert next(iter(reversed(dq))) == t[0] and len(list(dq)) == main._PAIR_SCAN_RECENT_MAX


def test_idle_sweep_frees_array():
    _reset()
    main._pair_scan_stats[("a", "X")] = [1, array.array("d", [100.0])]
    assert main._pair_scan_drop_idle(100.0 + main._PAIR_SCAN_WINDOW_SEC + 1) == 1
    assert main._pair_scan_stats[("a", "X")][1] == ()


def test_memory_is_smaller_than_deque():
    import collections
    import sys
    stamps = [1.0 * i for i in range(4)]
    dq = collections.deque(stamps, maxlen=400)
    arr = array.array("d", stamps)
    assert sys.getsizeof(arr) * 4 < sys.getsizeof(dq) + 24 * len(stamps)
