"""B-1604: live-basis re-measure (raw prices, real flatten time) at or below the strict floor closes the entry gate."""
import json

import main


def test_chan_gap_short_and_long_atr1d5_closed_others_open():
    failed = main._live_exit_remeasure_failed_tags()
    assert main.CHAN_GAP_SHORT_TAG in failed
    assert "chan_gap__buy_on_gap__long__1d__atr1d5_top10__v1" in failed
    assert "chan_gap__buy_on_gap__long__1d__atr4d0_top10__v1" not in failed
    assert "chan_gap__buy_on_gap__long__1d__atr2d5_top10__v1" not in failed
    assert main.CHAN_GAP_SHORT_TAG in main.REPLAY_FAILED_TAGS


def test_newest_run_decides_and_floor_is_strict(tmp_path, monkeypatch):
    d = tmp_path / "docs" / "backtest_data"
    d.mkdir(parents=True)
    (d / "live_exit_remeasure_run_1.json").write_text(json.dumps({"run_id": 1, "rows": [
        {"tag": "a", "n": 5, "pfnet": 0.5}, {"tag": "b", "n": 5, "pfnet": 1.0}, {"tag": "c", "n": 0, "pfnet": 0.1}]}))
    (d / "live_exit_remeasure_run_2.json").write_text(json.dumps({"run_id": 2, "rows": [{"tag": "a", "n": 5, "pfnet": 1.2}]}))
    monkeypatch.setattr(main.os.path, "abspath", lambda p: str(tmp_path / "main.py"))
    assert main._live_exit_remeasure_failed_tags() == frozenset({"b"})
