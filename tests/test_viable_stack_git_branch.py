import json
import main


def test_push_noop_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_SYNC_TOKEN", raising=False)
    assert main._push_viable_stack_to_git() is False


def test_newest_git_copy_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    old = {"stack": [{"created_at": 1, "label": "old", "names": ["a"]}]}
    new = {"stack": [{"created_at": 9, "label": "new", "names": ["b"]}]}

    class R:
        status_code = 200
        def json(self): return new
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: R())
    real_open = open
    def fake_open(path, *a, **k):
        if str(path).endswith("viable_stack.json"):
            p = tmp_path / "v.json"; p.write_text(json.dumps(old)); return real_open(p, *a, **k)
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    rows = main._viable_stack_git_rows()
    assert rows[-1]["label"] == "new"
