"""B-1639: account entity codes never reach the public repo."""
import sqlite3
from contextlib import closing

import main
import importlib.util, pathlib

REJ = "RMS:Rule: Check T1 holdings ,Used:4.00, Available:2.00  for entity account-AB1CD across exchange"


def test_redact_helper_masks_nested():
    out = main._redact_account_ids({"a": [REJ, 5], "b": None})
    assert main._redact_account_ids("GuiOrdId AB1CD-04b5b194-a2a6-4f67-9de5-e2aedc59dd02") == \
        "GuiOrdId ***-04b5b194-a2a6-4f67-9de5-e2aedc59dd02"
    assert "AB1CD" not in str(out) and "entity account-***" in out["a"][0] and out["a"][1] == 5 and out["b"] is None


def test_order_event_detail_is_masked(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **k: None)
    main.init_db()
    with closing(main.get_db()) as conn:
        main._log_real_order_event(conn, "X.NS", "sl", "failed", detail=REJ, new_state=REJ, reason="test")
        r = conn.execute("SELECT detail, new_state FROM real_order_events ORDER BY id DESC LIMIT 1").fetchone()
    assert "AB1CD" not in r["detail"] and "AB1CD" not in r["new_state"]


def test_script_masks_file(tmp_path):
    spec = importlib.util.spec_from_file_location("r", pathlib.Path(main.__file__).parent / "scripts/redact_account_ids.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    f = tmp_path / "log.json"; f.write_text('[{"detail": "%s"}]' % REJ)
    m.main([str(tmp_path)])
    assert "AB1CD" not in f.read_text() and "account-***" in f.read_text()
