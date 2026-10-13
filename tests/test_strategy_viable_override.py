import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import main
import strategy_registry as sr


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _post(body):
    r = MagicMock()

    async def _json():
        return body
    r.json = _json
    return asyncio.run(main.strategy_viable_override(r))


def test_stack_set_undo_restore_and_cap(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda only=None: 0)
    low = [d for d in sr.REGISTRY if d.metrics and d.metrics.pfnet < sr.PFNET_LIVE_FLOOR][:2]
    a, b = low[0], low[1]
    assert a.is_viable() is False
    _post({"action": "set", "names": [a.name, "no_such"]})
    assert a.is_viable() is True and b.is_viable() is False
    _post({"action": "set", "names": [b.name]})
    assert b.is_viable() is True and a.is_viable() is False   # newest replaces, earlier is second
    out = _post({"action": "undo"})
    assert a.is_viable() is True and b.is_viable() is False and len(out["stack"]) == 1
    out = _post({"action": "restore", "id": out["stack"][0]["id"]})
    assert len(out["stack"]) == 2
    for _ in range(15):
        out = _post({"action": "set", "names": [b.name]})
    assert len(out["stack"]) == main.VIABLE_STACK_SIZE == 10
    _post({"action": "undo"})
    while main.strategy_viable_stack_get()["stack"]:
        _post({"action": "undo"})
    assert a.is_viable() is False and b.is_viable() is False


def test_stack_table_is_mirrored():
    assert "strategy_viable_stack" in main._GENERIC_MIRROR_TABLES


def test_stack_relabel_renames_in_place(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda only=None: 0)
    a = [d for d in sr.REGISTRY if d.metrics][0]
    out = _post({"action": "set", "names": [a.name], "label": "explorer set"})
    sid = out["stack"][0]["id"]
    out = _post({"action": "relabel", "id": sid, "label": "pfnet(1.1-100), min(30), maxhold(18.75)"})
    assert out["stack"][0]["label"].startswith("pfnet(") and out["stack"][0]["id"] == sid
    assert out["stack"][0]["count"] == 1
