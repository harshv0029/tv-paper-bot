"""/trade-view is one page: fixed View 1/2/3 buttons on top, the chosen view (its own page) scrolls below."""
from fastapi.testclient import TestClient

import main


def test_trade_view_shell_has_three_fixed_tabs_and_views():
    cl = TestClient(main.app)
    r = cl.get("/trade-view")
    assert r.status_code == 200
    for v, src in (("v1", "/trade-view1"), ("v2", "/trade-view2"), ("v3", "/trade-view3")):
        assert f'data-v="{v}"' in r.text and f'data-src="{src}"' in r.text
    assert "position:fixed" in r.text and "no-store" in r.headers.get("cache-control", "")


def test_view1_keeps_the_original_dashboard_and_views_link_back_to_tabs():
    cl = TestClient(main.app)
    assert open("static/trade-view.html").read() == cl.get("/trade-view1").text
    for p in ("/trade-view2", "/trade-view3"):
        t = cl.get(p).text
        assert 'href="/trade-view#v1" target="_top"' in t
