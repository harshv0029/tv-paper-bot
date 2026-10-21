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
