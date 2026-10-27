"""B-1375: the newest saved viability definition is active straight after a restart, not after the first read."""
import inspect

import main


def test_startup_runs_the_stack_merge_before_journal_reconciles():
    src = inspect.getsource(main)
    i_hyd = src.index("asyncio.to_thread(hydrate_generic_tables_from_external)")
    i_merge = src.index("asyncio.to_thread(_startup_merge_viable_stack)")
    i_rec = src.index("    reconcile_open_positions_from_journal()\n    reconcile_trading_control_from_journal()")
    assert i_hyd < i_merge < i_rec


def test_startup_merge_clears_override_cache(monkeypatch):
    monkeypatch.setattr(main, "_viable_stack_merge_remote", lambda: 2)
    main._VIABLE_OVERRIDES_CACHE.update(key=("stale",), names={"x"})
    assert main._startup_merge_viable_stack() == 2
    assert main._VIABLE_OVERRIDES_CACHE == {}


def test_automatic_push_never_drops_a_newer_remote_save(monkeypatch, tmp_path):
    """Live 2026-10-27 08:32 IST: a stale post-restart table (21-Oct row only) overwrote the dedicated key."""
    import json
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE strategy_viable_stack (id INTEGER PRIMARY KEY, created_at REAL, label TEXT, names TEXT)")
    db.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (100, 'old', '[]')")

    class _C:  # closing() calls close(); keep the in-memory db alive
        def execute(self, *a): return db.execute(*a)
        def close(self): pass
    store = {main._VIABLE_STACK_REDIS_KEY: json.dumps([{"created_at": 100, "label": "old", "names": "[]"},
                                                       {"created_at": 200, "label": "new", "names": "[\"x\"]"}])}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "u")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "get_db", lambda: _C())
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    assert main._viable_stack_push_direct() is True
    assert [r["label"] for r in json.loads(store[main._VIABLE_STACK_REDIS_KEY])] == ["old", "new"]
    # the owner's own undo may drop rows
    assert main._viable_stack_push_direct(allow_drop=True) is True
    assert [r["label"] for r in json.loads(store[main._VIABLE_STACK_REDIS_KEY])] == ["old"]
