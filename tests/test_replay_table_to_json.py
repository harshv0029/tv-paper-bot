import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import replay_table_to_json as R  # noqa: E402
import missing_registry_tags as M  # noqa: E402

REASONS = "{'stop_hit': {'n': 10, 'pfnet': 0.0, 'win_pct': 0.0, 'avg_held_bars': 3.2}, 'target_hit': {'n': 4, 'pfnet': None, 'win_pct': 100.0, 'avg_held_bars': 7.0}}"
L1 = f"2026-10-14T05:12:33.4567890Z a__b__short__4h__atr3_h30_rr4__v1 n 14 pfnet 1.234 pfgross 2.5 win 40.5 hold_bars 5.5 {REASONS}"
L2 = f"2026-10-14T05:12:33.4567891Z c__d__long__1d__atr2__v1 n 3 pfnet inf pfgross 3.0 win 66.7 hold_h 12.5 {{}}"
NOISE = "2026-10-14T05:12:30.0000000Z ##[group]Run python3 merge\n2026-10-14T05:12:31.0000000Z Merging 8 shards"


def test_parses_timestamped_lines_keeping_every_field():
    rows, noise = R.parse_log(NOISE + "\n" + L1 + "\n" + L2 + "\n")
    assert noise == 2 and [r["tag"] for r in rows] == ["a__b__short__4h__atr3_h30_rr4__v1", "c__d__long__1d__atr2__v1"]
    m = rows[0]["metrics"]
    assert m["n"] == 14 and m["pfnet"] == 1.234 and m["pfgross"] == 2.5 and m["win_pct"] == 40.5
    assert m["avg_held_bars"] == 5.5 and "avg_held_hours" not in m
    assert m["exit_reasons"]["stop_hit"]["avg_held_bars"] == 3.2 and m["exit_reasons"]["target_hit"]["pfnet"] is None
    m2 = rows[1]["metrics"]
    assert m2["avg_held_hours"] == 12.5 and math.isinf(m2["pfnet"]) and m2["exit_reasons"] == {}


def test_build_schema_and_roundtrip(tmp_path):
    out = R.build(L1 + "\n" + L2, "log.txt", run_id="123", cost_pct=0.8, expect_rows=2)
    assert out["run_id"] == "123" and out["cost_round_trip_pct"] == 0.8 and len(out["rows"]) == 2
    p = tmp_path / "o.json"
    p.write_text(json.dumps(out))
    assert json.load(open(p))["rows"][0]["metrics"]["exit_reasons"]["stop_hit"]["n"] == 10


@pytest.mark.parametrize("bad", [
    "x__y__long__1d__atr2__v1 n 3 pfnet 1.0 win 50 hold_h 1 {}",                       # pfgross missing
    "x__y__long__1d__atr2__v1 n 3 pfnet abc pfgross 1 win 50 hold_h 1 {}",             # bad number
    "x__y__long__1d__atr2__v1 n 3 pfnet 1.0 pfgross 1 win 50 hold_h 1 {not a dict}",   # bad dict
    "x__y__long__1d__atr2__v1 n 3 pfnet 1.0 pfgross 1 win 50 hold_days 1 {}",          # unknown hold unit
    "x__y__long__1d__atr2__v1 n 3 pfnet None pfgross 1 win 50 hold_h 1 {}",            # missing core metric
])
def test_malformed_lines_refused_loudly(bad):
    with pytest.raises(ValueError) as ei:
        R.parse_log("noise\n" + bad)
    assert "line 2" in str(ei.value) or "None" in str(ei.value)


def test_duplicate_tag_and_empty_log_and_expect_rows():
    with pytest.raises(ValueError):
        R.parse_log(L1 + "\n" + L1)
    with pytest.raises(ValueError):
        R.build("nothing here", "x")
    with pytest.raises(ValueError):
        R.build(L1, "x", expect_rows=2)


def test_cli_exit_codes(tmp_path):
    good, bad, out = tmp_path / "g.txt", tmp_path / "b.txt", tmp_path / "o.json"
    good.write_text(L1 + "\n")
    bad.write_text("t__a__b__v1 n 1 pfnet 1\n")
    assert R.main([str(good), str(out), "--run-id", "9"]) == 0 and json.load(open(out))["run_id"] == "9"
    assert R.main([str(bad), str(out)]) == 2


def test_missing_registry_tags_report(tmp_path, capsys):
    d = tmp_path
    (d / "a.json").write_text(json.dumps({"rows": [{"tag": "never__registered__long__1d__atr2__v1", "metrics": {}},
                                                   {"tag": "universal_score"}],
                                          "cells": {"also__missing__short__5m__atr3__v2": {}}}))
    (d / "b.json").write_text("not json")
    names = {"universal_score"}
    per_file, skipped = M.scan(str(d), names)
    assert per_file["a.json"]["missing"] == ["also__missing__short__5m__atr3__v2", "never__registered__long__1d__atr2__v1"]
    assert [s["file"] for s in skipped] == ["b.json"]
    assert M.collect_tags({"x": {"tag": "UPPER__bad__v1"}}) == set()


def test_missing_report_runs_on_real_registry(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"rows": [{"tag": "zz_unregistered__probe__long__1d__atr2__v1"}]}))
    assert M.main(["--data-dir", str(tmp_path), "--fail-on-missing"]) == 1
    assert M.main(["--data-dir", str(tmp_path)]) == 0
