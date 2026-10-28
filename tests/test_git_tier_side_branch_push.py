import asyncio
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


def test_push_loop_is_independent_of_scheduler_tick(monkeypatch):
    """B-1349: the order-log push runs on its own wall-clock thread; a failing push never kills the loop."""
    calls = []
    monkeypatch.setattr(main, "_git_tier_push_side_branch", lambda n: calls.append(n) or (_ for _ in ()).throw(RuntimeError("x")))
    sleeps = []
    main._git_tier_push_loop(sleep=sleeps.append, rounds=3)
    assert calls == list(main._GIT_TIER_PUSH_TABLES) * 3 and sleeps == [60] * 3
    import inspect
    assert "_git_tier_push_side_branch" not in inspect.getsource(main._scheduler_tick)


def test_health_shows_order_log_push_age(monkeypatch):
    monkeypatch.setattr(main, "_git_tier_push_last_ok", {"real_order_events": main.time.time() - 30})
    assert 29 <= asyncio.run(main.health())["order_log_git_push_age_s"] <= 31


def test_order_event_wakes_git_push_immediately(monkeypatch, tmp_path):
    """B-1355: logging an order event wakes the git push thread at once (not after up to 60 s)."""
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "w.db"))
    main.init_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **k: None)
    # Fresh Event: a push thread started by an earlier test in this process could consume the shared one.
    monkeypatch.setattr(main, "_git_tier_push_wake", main.threading.Event())
    with main.closing(main.get_db()) as c:
        main._log_real_order_event(c, "X.NS", "exit", "intent", reason="test")
    assert main._git_tier_push_wake.is_set()
    main._git_tier_push_wait(0)
    assert not main._git_tier_push_wake.is_set()


def test_unchanged_log_counts_as_in_sync(monkeypatch, tmp_path):
    """B-1360: after the close no new order events arrive; an unchanged, already-pushed log is in sync, not stale."""
    put = _setup(monkeypatch, tmp_path, [{"ts": 2.0, "symbol": "B", "leg": "exit", "event": "confirmed", "order_id": "o2"}], [])
    monkeypatch.setattr(main, "_git_tier_push_last_ok", {})
    assert main._git_tier_push_side_branch("real_order_events") is True
    main._git_tier_push_last_ok["real_order_events"] = main.time.time() - 3600
    put.clear()
    assert main._git_tier_push_side_branch("real_order_events") is False
    assert not put  # nothing re-pushed
    assert main._git_tier_push_status()["order_log_git_push_age_s"] < 5
