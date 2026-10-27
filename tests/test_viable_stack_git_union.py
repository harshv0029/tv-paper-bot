"""B-1377: the side-branch git push of the viable stack is a union with the remote copy, like the Redis key push."""
import base64
import json
import sqlite3

import pytest

import main


class _Resp:
    def __init__(self, status, data=None, raw=None):
        self.status_code = status
        self._data = data
        self._raw = raw

    def json(self):
        if self._raw is not None:
            return {"sha": "s1", "content": self._raw}
        return {"sha": "s1", "content": base64.b64encode(json.dumps(self._data).encode()).decode()}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def env(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE strategy_viable_stack (id INTEGER PRIMARY KEY, created_at REAL, label TEXT, names TEXT)")
    db.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (100, 'old', '[\"a\"]')")

    class _C:
        def execute(self, *a): return db.execute(*a)
        def close(self): pass
    monkeypatch.setattr(main, "get_db", lambda: _C())
    monkeypatch.setenv("GITHUB_SYNC_TOKEN", "tok")
    st = {"get": None, "puts": []}

    def fake_get(url, *a, **k):
        return st["get"]

    def fake_put(url, *a, json=None, **k):
        st["puts"].append(json)
        return _Resp(200, {})
    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "put", fake_put)
    return st


def _pushed_labels(st):
    body = json.loads(base64.b64decode(st["puts"][-1]["content"]).decode())
    return [r["label"] for r in body["stack"]]


def test_newer_remote_row_is_preserved(env):
    env["get"] = _Resp(200, {"size": 10, "stack": [{"id": 7, "created_at": 200, "label": "new", "names": ["x"]},
                                                   {"id": 1, "created_at": 100, "label": "old", "names": ["a"]}]})
    assert main._push_viable_stack_to_git() is True
    assert _pushed_labels(env) == ["new", "old"]
    assert env["puts"][-1]["sha"] == "s1"


def test_allow_drop_overwrites_remote(env):
    env["get"] = _Resp(200, {"size": 10, "stack": [{"id": 7, "created_at": 200, "label": "new", "names": ["x"]}]})
    assert main._push_viable_stack_to_git(allow_drop=True) is True
    assert _pushed_labels(env) == ["old"]


def test_remote_read_failure_skips_push(env):
    env["get"] = _Resp(500)
    assert main._push_viable_stack_to_git() is False
    assert env["puts"] == []


def test_undecodable_remote_skips_push(env):
    env["get"] = _Resp(200, raw="!!!not-base64-json")
    assert main._push_viable_stack_to_git() is False
    assert env["puts"] == []


def test_union_keeps_newest_stack_size(env):
    remote = [{"id": i, "created_at": 1000 + i, "label": f"r{i}", "names": []} for i in range(main.VIABLE_STACK_SIZE)]
    env["get"] = _Resp(200, {"stack": remote})
    assert main._push_viable_stack_to_git() is True
    labels = _pushed_labels(env)
    assert len(labels) == main.VIABLE_STACK_SIZE and "old" not in labels and labels[0] == f"r{main.VIABLE_STACK_SIZE - 1}"


def test_override_endpoint_pushes_git_with_allow_drop():
    import inspect
    src = inspect.getsource(main)
    assert 'target=_push_viable_stack_to_git, kwargs={"allow_drop": True}' in src
