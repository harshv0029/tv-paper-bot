import json
from contextlib import closing

import main


def _count():
    from contextlib import closing
    with closing(main.get_db()) as c:
        return c.execute("SELECT COUNT(*) FROM strategy_viable_stack").fetchone()[0]


def test_git_file_restores_empty_stack(tmp_path, monkeypatch):
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM strategy_viable_stack")
        c.commit()
    monkeypatch.setattr(main, "hydrate_generic_tables_from_external", lambda: 0)
    main._VIABLE_STACK_RECOVER_LAST = 0.0
    monkeypatch.setattr(main, "_VIABLE_STACK_GIT_RESTORE_IN_TESTS", True)
    monkeypatch.setattr(main.os.path, "abspath", lambda p: str(tmp_path / "main.py"))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "viable_stack.json").write_text(json.dumps(
        {"stack": [{"created_at": 1.0, "label": "pfnet(1.1-99), min(5), maxhold(any)", "names": []}]}))
    try:
        main._ensure_viable_stack_hydrated()
        assert _count() == 1
    finally:
        with closing(main.get_db()) as c:
            c.execute("DELETE FROM strategy_viable_stack")
            c.commit()
        main._load_viable_overrides()


def test_direct_key_round_trip(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "y")
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM strategy_viable_stack")
        c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (1.0, 'pfnet(1.04-100), min(30), maxhold(6)', '[]')")
        c.commit()
    try:
        assert main._viable_stack_push_direct() is True
        with closing(main.get_db()) as c:
            c.execute("DELETE FROM strategy_viable_stack")  # simulated wipe
            c.commit()
        assert main._restore_viable_stack_direct() == 1
        assert _count() == 1
        assert main._viable_stack_push_direct() is True
    finally:
        with closing(main.get_db()) as c:
            c.execute("DELETE FROM strategy_viable_stack")
            c.commit()
        main._load_viable_overrides()
