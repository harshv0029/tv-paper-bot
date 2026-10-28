"""B-1407: today's strategy scan counts survive a Render restart via Render's own state-sync push."""
import base64
import json

import main
from tests.test_git_tier_side_branch_push import _R


def _today():
    return main.ist_now().strftime("%Y-%m-%d")


def test_scan_counts_are_pushed_by_render(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "s.db"))
    main.init_db()
    d = _today()
    with main.closing(main.get_db()) as c:
        c.execute("INSERT INTO strategy_scan_counts (day, tag, n) VALUES (?,?,?)", (d, "gap_and_go", 50))
        c.commit()
    monkeypatch.setenv("GITHUB_SYNC_TOKEN", "x")
    monkeypatch.setattr(main, "_git_tier_hydrated", {"strategy_scan_counts"})
    monkeypatch.setattr(main, "_git_tier_push_last_hash", {})
    remote = [{"day": d, "tag": "gap_and_go", "n": 400}, {"day": d, "tag": "chan_gap", "n": 7},
              {"day": "2000-01-01", "tag": "old", "n": 1}]
    content = base64.b64encode(json.dumps({"rows": remote}).encode()).decode()
    put = {}
    monkeypatch.setattr(main.requests, "get", lambda url, **k: _R(200, {"sha": "s", "content": content}))
    monkeypatch.setattr(main.requests, "put", lambda url, **k: put.update(k["json"]) or _R(200, {}))
    assert main._git_tier_push_side_branch("strategy_scan_counts") is True
    rows = json.loads(base64.b64decode(put["content"]))["rows"]
    got = {r["tag"]: r["n"] for r in rows}
    # a post-restart partial local count never lowers the git copy; old days are pruned
    assert got == {"gap_and_go": 400, "chan_gap": 7}
    assert put["branch"] == "state-sync"


def test_restart_restores_todays_counts_from_side_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "h.db"))
    main.init_db()
    d = _today()
    monkeypatch.setattr(main, "_git_tier_hydrated", set(t for t in main._GENERIC_MIRROR_GIT_TIER if t != "strategy_scan_counts"))
    main_rows = [{"day": d, "tag": "gap_and_go", "n": 10}]  # stale cron copy on main
    side_rows = [{"day": d, "tag": "gap_and_go", "n": 404}, {"day": d, "tag": "chan_gap", "n": 9}]
    monkeypatch.setattr(main.requests, "get",
                        lambda url, **k: _R(200, {"rows": side_rows if "/state-sync/" in url else main_rows}))
    main.hydrate_git_tier_tables()
    monkeypatch.setattr(main, "_strategy_scan_counts", {})
    monkeypatch.setattr(main, "_strategy_scan_counts_day", "")
    with main.closing(main.get_db()) as c:
        main._restore_strategy_scan_counts(c)
    assert main._strategy_scan_counts == {"gap_and_go": 404, "chan_gap": 9}


def test_push_loop_flushes_memory_counts_only_after_restore(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "f.db"))
    main.init_db()
    monkeypatch.setattr(main, "_git_tier_push_side_branch", lambda n: False)
    monkeypatch.setattr(main, "_strategy_scan_counts", {"orb-range-short": 3})
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    main._git_tier_push_loop(sleep=lambda s: None, rounds=1)
    with main.closing(main.get_db()) as c:
        assert c.execute("SELECT COUNT(*) FROM strategy_scan_counts").fetchone()[0] == 0  # restore still pending
    monkeypatch.setattr(main, "_git_tier_hydrated", {"strategy_scan_counts"})
    main._git_tier_push_loop(sleep=lambda s: None, rounds=1)
    with main.closing(main.get_db()) as c:
        assert c.execute("SELECT n FROM strategy_scan_counts WHERE tag='orb-range-short'").fetchone()[0] == 3
