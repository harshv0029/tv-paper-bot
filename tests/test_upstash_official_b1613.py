"""B-1613: View 4's cumulative Upstash usage comes from Upstash's Developer API when the management key is set."""
import os
from unittest.mock import patch

import main


class _R:
    def __init__(self, j): self._j = j
    def raise_for_status(self): pass
    def json(self): return self._j


def _get(url):
    if url.endswith("/databases"):
        return _R([{"database_id": "other", "endpoint": "x.upstash.io"},
                   {"database_id": "db2", "endpoint": "big-cat-1.upstash.io", "database_name": "nov"}])
    assert url.endswith("/stats/db2"), url
    return _R({"total_monthly_bandwidth": 3_400_000_000, "total_monthly_requests": 120000, "total_monthly_billing": 0})


def test_b1613_reads_month_bandwidth_of_the_active_database():
    main._UPSTASH_OFFICIAL_CACHE.update(at=0.0, url="", data=None, error=None)
    with patch.dict(os.environ, {"UPSTASH_MGMT_EMAIL": "e", "UPSTASH_MGMT_API_KEY": "k"}), \
            patch.object(main, "UPSTASH_REDIS_REST_URL", "https://big-cat-1.upstash.io"):
        d = main._upstash_official_month(http_get=_get, now=1e9)
        assert d["month_bandwidth_bytes"] == 3_400_000_000 and d["month_requests"] == 120000
        assert main._upstash_official_month(http_get=lambda u: 1 / 0, now=1e9 + 60) == d  # cached 15 min


def test_b1613_no_key_or_failure_keeps_endpoint_working():
    main._UPSTASH_OFFICIAL_CACHE.update(at=0.0, url="", data=None, error=None)
    with patch.dict(os.environ, {"UPSTASH_MGMT_EMAIL": "", "UPSTASH_MGMT_API_KEY": ""}):
        assert main._upstash_official_month() is None and "not set" in main._UPSTASH_OFFICIAL_CACHE["error"]
        out = main.upstash_usage()
        assert out["upstash_official"] is None and out["month_used_bytes"] is not None
    with patch.dict(os.environ, {"UPSTASH_MGMT_EMAIL": "e", "UPSTASH_MGMT_API_KEY": "k"}), \
            patch.object(main, "UPSTASH_REDIS_REST_URL", "https://big-cat-1.upstash.io"):
        assert main._upstash_official_month(http_get=lambda u: 1 / 0, now=2e9) is None
        assert "ZeroDivisionError" in main._UPSTASH_OFFICIAL_CACHE["error"]


def test_b1613_view4_prefers_official_figure():
    s = open(os.path.join(os.path.dirname(__file__), "..", "static", "trade-view4.html")).read()
    assert "upstash_official.month_bandwidth_bytes" in s and "from Upstash" in s
