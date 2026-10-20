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
