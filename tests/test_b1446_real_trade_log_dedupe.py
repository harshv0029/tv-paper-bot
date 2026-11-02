"""B-1446: docs/real_trade_log.json froze at 696 entries (27 Oct 2026) because
journal-sync.yml deduped real_trades rows by id alone. real_trades' AUTOINCREMENT
id restarts after a Render wipe, so new attempts with colliding ids were dropped.
Runs the workflow's own jq program on fixtures."""
import json
import os
import re
import shutil
import subprocess

import pytest

WF = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "journal-sync.yml")

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


def _jq_program():
    text = open(WF).read()
    m = re.search(r"jq -s '(.*?)'\s+docs/real_trade_log\.json /tmp/real-trades\.json", text, re.S)
    assert m, "real_trade_log merge step not found in journal-sync.yml"
    return m.group(1)


def _merge(tmp_path, existing, fetched):
    a = tmp_path / "existing.json"
    b = tmp_path / "fetched.json"
    a.write_text(json.dumps(existing))
    b.write_text(json.dumps({"count": len(fetched), "trades": fetched}))
    out = subprocess.run(["jq", "-s", _jq_program(), str(a), str(b)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _row(i, ts, sym, status="confirmed", order_id=None):
    return {"id": i, "ts": ts, "day": "2026-10-27", "symbol": sym,
            "status": status, "order_id": order_id}


def test_new_rows_with_reused_ids_after_wipe_are_kept(tmp_path):
    old = [_row(1, 1000.0, "A.NS"), _row(2, 1001.0, "B.NS")]
    new_after_wipe = [_row(1, 2000.0, "C.NS"), _row(2, 2001.0, "D.NS", "skipped_no_live_tick")]
    merged = _merge(tmp_path, old, new_after_wipe)
    assert [r["symbol"] for r in merged] == ["A.NS", "B.NS", "C.NS", "D.NS"]


def test_rerun_does_not_double_append(tmp_path):
    rows = [_row(1, 1000.0, "A.NS"), _row(2, 1001.0, "B.NS", order_id="X1")]
    once = _merge(tmp_path, [], rows)
    twice = _merge(tmp_path, once, rows)
    assert twice == once and len(twice) == 2


def test_empty_fetch_keeps_existing(tmp_path):
    old = [_row(5, 1000.0, "A.NS")]
    assert _merge(tmp_path, old, []) == old
