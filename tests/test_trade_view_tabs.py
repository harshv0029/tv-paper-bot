"""/trade-view is one page: fixed View 1/2/3 buttons on top, the chosen view (its own page) scrolls below."""
from fastapi.testclient import TestClient

import main


def test_trade_view_shell_has_three_fixed_tabs_and_views():
    cl = TestClient(main.app)
    r = cl.get("/trade-view")
    assert r.status_code == 200
    for v, src in (("v1", "/trade-view1"), ("v2", "/trade-view2"), ("v3", "/trade-view3"), ("v4", "/trade-view4")):
        assert f'data-v="{v}"' in r.text and f'data-src="{src}"' in r.text
    assert "position:fixed" in r.text and "no-store" in r.headers.get("cache-control", "")


def test_view1_keeps_the_original_dashboard_and_views_link_back_to_tabs():
    cl = TestClient(main.app)
    assert open("static/trade-view.html").read() == cl.get("/trade-view1").text
    for p in ("/trade-view2", "/trade-view3", "/trade-view4"):
        t = cl.get(p).text
        assert 'href="/trade-view#v1" target="_top"' in t


def test_view4_polls_the_live_read_only_feeds():
    t = TestClient(main.app).get("/trade-view4").text
    for u in ("/algo-live-flow", "/scheduler-pipeline", "/real-order-log", "/real-protection-status", "/real-open-positions"):
        assert u in t
    assert "method:" not in t  # read-only: no POST from this page


def test_algo_live_flow_returns_real_sequence_and_scan_events():
    main._pair_scan_stats[("unit_tag", "UNIT.NS")] = [1, main.collections.deque([main.time.time()])]
    try:
        d = TestClient(main.app).get("/algo-live-flow").json()
    finally:
        main._pair_scan_stats.pop(("unit_tag", "UNIT.NS"), None)
    assert d["flat_count"] == len(d["sequence"]) or len(d["sequence"]) <= 38
    assert {"symbol", "strategy", "offset"} <= set(d["sequence"][0])
    assert {"ts": d["scan_events"][0]["ts"], "tag": "unit_tag", "symbol": "UNIT.NS"} in d["scan_events"]


def test_algo_live_flow_burst_cannot_crowd_out_other_symbols_and_reports_daily_coverage():
    """B-1336: a 180-cell daily burst on one symbol used to fill the 400-event cap; each symbol is now capped and
    today's distinct-tag coverage plus swing-pass skips are returned."""
    now = main.time.time()
    keys = [(f"burst_{i}", "BURST.NS") for i in range(180)] + [("rr_tag", "QUIET.NS")]
    for k in keys:
        main._pair_scan_stats[k] = [1, main.collections.deque([now])]
    day = main.ist_now().strftime("%Y-%m-%d")
    saved_day, saved_scans = main._symbol_strategy_scans_day, dict(main._symbol_strategy_scans)
    main._symbol_strategy_scans_day = day
    main._symbol_strategy_scans.update({"BURST.NS": {f"burst_{i}" for i in range(180)}, "QUIET.NS": {"rr_tag"}})
    main._note_swing_skipped("SKIP.NS", "daily fetch failed")
    try:
        d = TestClient(main.app).get("/algo-live-flow").json()
    finally:
        for k in keys:
            main._pair_scan_stats.pop(k, None)
        main._symbol_strategy_scans.clear()
        main._symbol_strategy_scans.update(saved_scans)
        main._symbol_strategy_scans_day = saved_day
        main._swing_skipped_today["syms"].pop("SKIP.NS", None)
    assert d["window_scans_by_symbol"]["BURST.NS"] == 180
    assert sum(1 for e in d["scan_events"] if e["symbol"] == "BURST.NS") <= 40
    assert any(e["symbol"] == "QUIET.NS" for e in d["scan_events"])
    assert d["tested_today_by_symbol"]["BURST.NS"] == 180 and d["tested_today_by_symbol"]["QUIET.NS"] == 1
    assert d["tested_today_max"] >= 180
    assert d["swing_skipped_today"]["SKIP.NS"] == "daily fetch failed"
    assert 'id="tagCov"' in open("static/trade-view4.html").read()
