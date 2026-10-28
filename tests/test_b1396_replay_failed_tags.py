"""B-1396: a tag whose main.py replay is on file but below PFNET_LIVE_FLOOR is no longer "replay owed"; it is a
separate, still-closed REPLAY_FAILED set. Replay files keep metrics nested or flat; both must be read."""
import json
import types

import main
import strategy_registry as sr


def _files(tmp_path, monkeypatch, rows_by_file):
    d = tmp_path / "docs" / "backtest_data"
    d.mkdir(parents=True)
    for name, rows in rows_by_file.items():
        (d / name).write_text(json.dumps({"rows": rows}))
    monkeypatch.setattr(main.os.path, "abspath", lambda p: str(tmp_path / "main.py") if p == main.__file__ else p)


def test_flat_and_nested_rows_are_both_read(tmp_path, monkeypatch):
    _files(tmp_path, monkeypatch, {
        "a_main_replay_run_1.json": [{"tag": "flat_fail", "n": 50, "pfnet": 0.68}],
        "b_main_replay_run_2.json": [{"tag": "nested_pass", "metrics": {"n": 40, "pfnet": sr.PFNET_LIVE_FLOOR + 0.2}}],
    })
    rows = {t: (n, pf) for t, n, pf in main._replay_rows()}
    assert rows == {"flat_fail": (50, 0.68), "nested_pass": (40, sr.PFNET_LIVE_FLOOR + 0.2)}
    assert main._replay_verified_tags() == frozenset({"nested_pass"})
    assert main._replay_failed_tags() == frozenset({"flat_fail"})


def test_a_later_passing_run_overrides_an_earlier_failing_one(tmp_path, monkeypatch):
    _files(tmp_path, monkeypatch, {
        "a_main_replay_run_1.json": [{"tag": "t", "metrics": {"n": 10, "pfnet": 0.5}}],
        "a_main_replay_run_2.json": [{"tag": "t", "metrics": {"n": 10, "pfnet": sr.PFNET_LIVE_FLOOR}}],
    })
    assert main._replay_failed_tags() == frozenset()
    assert main._replay_verified_tags() == frozenset({"t"})


def test_zero_trade_replay_neither_verifies_nor_fails(tmp_path, monkeypatch):
    _files(tmp_path, monkeypatch, {"a_main_replay_run_1.json": [{"tag": "t", "metrics": {"n": 0, "pfnet": 0}}]})
    assert main._replay_failed_tags() == frozenset() and main._replay_verified_tags() == frozenset()


def test_gate_blocks_replay_failed_tag_with_its_own_reason(monkeypatch):
    m = types.SimpleNamespace(pfnet=2.0)
    strat = types.SimpleNamespace(metrics=m, is_viable=lambda: True)
    monkeypatch.setattr(main, "_STRATEGY_TAG_TO_REGISTRY_NAME", {"tag_x": "reg_x"})
    monkeypatch.setattr(main, "_registry_entry", lambda n: strat if n == "reg_x" else None)
    monkeypatch.setattr(main, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", False)
    monkeypatch.setattr(main, "REPLAY_OWED_TAGS", frozenset())
    monkeypatch.setattr(main, "REPLAY_FAILED_TAGS", frozenset({"tag_x"}))
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    assert main._viability_verdict("tag_x", check_switch=False) == (False, "replay_below_floor")


def test_live_macddiv_cells_are_replay_failed_not_owed():
    for t in main.MACDDIV_LONG_CELLS:
        assert t not in main.REPLAY_OWED_TAGS and t in main.REPLAY_FAILED_TAGS
