"""B-1336: View 4 per-symbol check counts come from the durable per-IST-day counters, not the 2-min live window."""
import os
from unittest.mock import patch

import main

VIEW4 = os.path.join(os.path.dirname(__file__), "..", "static", "trade-view4.html")


def _seed(day):
    main._symbol_strategy_scans.clear()
    main._pair_scan_stats.clear()
    main._scheduler_check_counts.clear()
    main._symbol_strategy_scans_day = day
    main._pair_scan_day = day
    main._scheduler_check_counts_day = day
    main._symbol_strategy_scans.update({"SUNPHARMA.NS": {f"t{i}" for i in range(181)}, "EICHERMOT.NS": {"t0", "t1"}})
    for i in range(181):
        main._pair_scan_stats[(f"t{i}", "SUNPHARMA.NS")] = [2, ()]  # restored count, deque already freed
    main._pair_scan_stats[("t0", "EICHERMOT.NS")] = [5, ()]
    main._scheduler_check_counts.update({"EICHERMOT.NS": 40, "EICHERMOT.NS:STRIKE": 3, "SUNPHARMA.NS": 7})


def test_per_day_counts_by_symbol_independent_of_live_window():
    today = main.ist_now().strftime("%Y-%m-%d")
    saved = (dict(main._symbol_strategy_scans), dict(main._pair_scan_stats), dict(main._scheduler_check_counts),
             main._symbol_strategy_scans_day, main._pair_scan_day, main._scheduler_check_counts_day)
    try:
        _seed(today)
        d = main.symbol_check_counts_today()
        by = d["by_symbol"]
        assert d["day_ist"] == today
        assert by["SUNPHARMA.NS"] == {"strategies_tested": 181, "strategy_scans": 362, "scheduler_checks": 7}
        assert by["EICHERMOT.NS"] == {"strategies_tested": 2, "strategy_scans": 5, "scheduler_checks": 43}
        assert d["strategies_tested_max"] == 181 and d["strategies_tested_min"] == 2 and d["symbols"] == 2
        # nothing scanned in the last 2 min: the live window is empty but the day counts are unchanged
        assert main.algo_live_flow(window=120)["scan_events"] == []
    finally:
        main._symbol_strategy_scans.clear(); main._symbol_strategy_scans.update(saved[0])
        main._pair_scan_stats.clear(); main._pair_scan_stats.update(saved[1])
        main._scheduler_check_counts.clear(); main._scheduler_check_counts.update(saved[2])
        main._symbol_strategy_scans_day, main._pair_scan_day, main._scheduler_check_counts_day = saved[3:]


def test_previous_day_counters_read_as_zero():
    saved = (dict(main._symbol_strategy_scans), dict(main._pair_scan_stats), dict(main._scheduler_check_counts),
             main._symbol_strategy_scans_day, main._pair_scan_day, main._scheduler_check_counts_day)
    try:
        _seed("2000-01-01")
        d = main.symbol_check_counts_today()
        assert d["by_symbol"] == {} and d["strategies_tested_max"] == 0
    finally:
        main._symbol_strategy_scans.clear(); main._symbol_strategy_scans.update(saved[0])
        main._pair_scan_stats.clear(); main._pair_scan_stats.update(saved[1])
        main._scheduler_check_counts.clear(); main._scheduler_check_counts.update(saved[2])
        main._symbol_strategy_scans_day, main._pair_scan_day, main._scheduler_check_counts_day = saved[3:]


def test_counts_survive_restart_via_upstash_hydrate():
    """The sources are the already-mirrored per-day blobs: a simulated wipe + hydrate restores the per-day counts."""
    today = main.ist_now().strftime("%Y-%m-%d")
    store = {}
    saved = (dict(main._symbol_strategy_scans), dict(main._pair_scan_stats),
             main._symbol_strategy_scans_day, main._pair_scan_day)
    try:
        with patch.object(main, "UPSTASH_REDIS_REST_URL", "x"), patch.object(main, "UPSTASH_REDIS_REST_TOKEN", "y"), \
                patch.object(main, "_upstash_set", lambda k, v: store.__setitem__(k, v)), \
                patch.object(main, "_upstash_get", lambda k: store.get(k)), \
                patch.object(main, "_symbol_scans_last_digest", None), patch.object(main, "_pair_scans_last_digest", None):
            _seed(today)
            main._symbol_scans_push_now(); main._pair_scans_push_now()
            main._symbol_strategy_scans.clear(); main._pair_scan_stats.clear()  # Render restart
            main._symbol_strategy_scans_day = main._pair_scan_day = ""
            assert main._symbol_scans_hydrate_now() and main._pair_scans_hydrate_now()
            by = main.symbol_check_counts_today()["by_symbol"]
            assert by["SUNPHARMA.NS"]["strategies_tested"] == 181 and by["SUNPHARMA.NS"]["strategy_scans"] == 362
            assert by["EICHERMOT.NS"]["strategies_tested"] == 2
    finally:
        main._symbol_strategy_scans.clear(); main._symbol_strategy_scans.update(saved[0])
        main._pair_scan_stats.clear(); main._pair_scan_stats.update(saved[1])
        main._symbol_strategy_scans_day, main._pair_scan_day = saved[2:]


def test_endpoint_routed():
    from fastapi.testclient import TestClient
    r = TestClient(main.app).get("/symbol-check-counts-today")
    assert r.status_code == 200 and {"day_ist", "by_symbol", "strategies_tested_max"} <= set(r.json())


def test_view4_uses_per_day_endpoint_and_labels_today_ist():
    s = open(VIEW4).read()
    assert '"/symbol-check-counts-today"' in s and "today (IST" in s and 'id="covList"' in s
    assert "last 2 min (live)" in s  # the live-flow view keeps its recent-events role, labelled as such
    assert '"/algo-live-flow?window=120' in s
