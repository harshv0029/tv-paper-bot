import pytest
from fastapi import HTTPException

import main


def test_export_refused_until_restored(monkeypatch):
    """B-1326: a git-tier table is not exported before its git restore ran."""
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    with pytest.raises(HTTPException) as e:
        main.table_export_endpoint("real_order_events")
    assert e.value.status_code == 503


def test_export_after_restore(monkeypatch):
    monkeypatch.setattr(main, "_git_tier_hydrated", {"real_order_events"})
    out = main.table_export_endpoint("real_order_events")
    assert out["count"] == len(out["rows"])
