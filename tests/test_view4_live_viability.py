"""B-1370 (2026-10-26): View 4 shows the live viability condition read from the running bot."""
import os
import tempfile
from unittest.mock import patch

import main


def test_stack_endpoint_carries_live_gate():
    from fastapi.testclient import TestClient
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    with patch.object(main, "DB_PATH", path):
        main.init_db()
        g = TestClient(main.app).get("/strategy-viable-stack").json()["live_gate"]
    import strategy_registry as sr
    assert g["wiring_pfnet_floor"] == sr.PFNET_LIVE_FLOOR
    assert g["requires_explorer_stack"] is main.REAL_ENTRY_REQUIRES_EXPLORER_STACK
    assert {"trading_enabled", "stack_active", "active_names", "replay_owed_tags", "checked_at"} <= set(g)


def test_view4_polls_live_viability():
    s = open(os.path.join(os.path.dirname(__file__), "..", "static", "trade-view4.html")).read()
    assert 'id="viaTxt"' in s and "pollViability" in s and "live_gate" in s
