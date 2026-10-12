import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import marked_ledger_merge_research as M  # noqa: E402


def _shard(tmp, n):
    streams = {"b|long|2": [[1, 3, 0.1, 0.05, 2, 100.0, 1e6, "target", "A"]]}
    paths = {"b|long|2": [[[1, 2, 3], [100.0, 105.0, 110.0]]]}
    json.dump({"fetched": 1, "universe": 2, "streams": streams, "paths": paths}, open(tmp / f"collect_{n}.json", "w"))


def test_merge_marked_runs_ledger_and_keeps_stats(tmp_path):
    _shard(tmp_path, 0)
    _shard(tmp_path, 1)
    out = M.merge_marked(str(tmp_path), str(tmp_path / "o.json"))
    r = out["rows"][0]
    assert out["universe"] == 4 and r["stats"]["n"] == 2 and r["ledger"]["final_equity"] > 1.0
    assert r["ledger"]["closes_by_reason"] == {"exit": 2}
    assert json.load(open(tmp_path / "o.json"))["rows"][0]["key"] == "b|long|2"


def test_merge_marked_requires_marks(tmp_path):
    json.dump({"fetched": 1, "universe": 1, "streams": {"b|long|2": []}}, open(tmp_path / "collect_0.json", "w"))
    with pytest.raises(SystemExit):
        M.merge_marked(str(tmp_path))
