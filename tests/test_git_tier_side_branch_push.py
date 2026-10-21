import base64
import json

import main


class _R:
    def __init__(self, code, data=None):
        self.status_code, self._d, self.text = code, data, json.dumps(data or {})

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _setup(monkeypatch, tmp_path, local_rows, remote_rows):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    main.init_db()
    with main.closing(main.get_db()) as c:
        for r in local_rows:
            c.execute("INSERT INTO real_order_events (ts, symbol, leg, event, order_id, detail) VALUES (?,?,?,?,?,?)",
                      (r["ts"], r["symbol"], r["leg"], r["event"], r["order_id"], r.get("detail")))
        c.commit()
    monkeypatch.setenv("GITHUB_SYNC_TOKEN", "x")
    monkeypatch.setattr(main, "_git_tier_hydrated", {"real_order_events"})
    monkeypatch.setattr(main, "_git_tier_push_last_hash", {})
    put = {}
    content = base64.b64encode(json.dumps({"rows": remote_rows}).encode()).decode()
    monkeypatch.setattr(main.requests, "get", lambda url, **k: _R(200, {"sha": "s", "content": content}))
    monkeypatch.setattr(main.requests, "put", lambda url, **k: put.update(k["json"]) or _R(200, {}))
    return put


def test_push_is_append_only(monkeypatch, tmp_path):
    """B-1327: a wiped local table holding only new rows never drops older rows from the git copy."""
    old = {"id": 1, "ts": 1.0, "symbol": "A", "leg": "entry", "event": "confirmed", "order_id": "o1"}
    new = {"ts": 2.0, "symbol": "B", "leg": "exit", "event": "confirmed", "order_id": "o2"}
    put = _setup(monkeypatch, tmp_path, [new], [old])
    assert main._git_tier_push_side_branch("real_order_events") is True
    rows = json.loads(base64.b64decode(put["content"]))["rows"]
    assert [r["order_id"] for r in rows] == ["o1", "o2"]
    assert put["branch"] == "state-sync" and put["sha"] == "s"


def test_push_refused_before_restore(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [{"ts": 2.0, "symbol": "B", "leg": "exit", "event": "confirmed", "order_id": "o2"}], [])
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    assert main._git_tier_push_side_branch("real_order_events") is False


def test_no_token_no_push(monkeypatch):
    monkeypatch.delenv("GITHUB_SYNC_TOKEN", raising=False)
    assert main._git_tier_push_side_branch("real_order_events") is False


def test_hydrate_merges_side_branch(monkeypatch, tmp_path):
    """B-1327: an empty order log restores from main's copy AND Render's state-sync copy, without id clashes."""
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "h.db"))
    main.init_db()
    monkeypatch.setattr(main, "_git_tier_hydrated", set(t for t in main._GENERIC_MIRROR_GIT_TIER if t != "real_order_events"))
    main_rows = [{"id": 1, "ts": 1.0, "symbol": "A", "leg": "entry", "event": "confirmed", "order_id": "o1"}]
    side_rows = [{"id": 1, "ts": 2.0, "symbol": "B", "leg": "exit", "event": "confirmed", "order_id": "o2"},
                 {"id": 9, "ts": 1.0, "symbol": "A", "leg": "entry", "event": "confirmed", "order_id": "o1"}]
    monkeypatch.setattr(main.requests, "get",
                        lambda url, **k: _R(200, {"rows": side_rows if "/state-sync/" in url else main_rows}))
    main.hydrate_git_tier_tables()
    with main.closing(main.get_db()) as c:
        got = sorted(r[0] for r in c.execute("SELECT order_id FROM real_order_events").fetchall())
    assert got == ["o1", "o2"]
