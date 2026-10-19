import os
import tempfile

import main


def test_entry_funnel_counts_skip_reasons_without_details(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    monkeypatch.setattr(main, "strategy_scan_activity", lambda include_unwired=False: {"strategies": [
        {"strategy_tag": "t1", "categories": ["swing"], "status": "live_wired", "scans_today": 5, "successful_entries_today": 1}]})
    conn = main.get_db()
    main._log_real_attempt(conn, "AAA.NS", "B", "skipped_insufficient_real_qty", detail="capital Rs1234 secret", strategy="t1")
    main._log_real_attempt(conn, "BBB.NS", "B", "skipped_insufficient_real_qty", strategy="t1")
    conn.close()
    d = main.entry_funnel()["categories"]
    sw = d["swing"]
    assert sw["attempts"][0]["status"] == "skipped_insufficient_real_qty" and sw["attempts"][0]["attempts"] == 2
    assert sw["scans_today"] == 5 and sw["paper_entries_today"] == 1 and sw["blocked"] == 2
    assert "no viable" in d["buy"]["verdict"] and d["buy"]["attempts"] == []
    assert "secret" not in str(d) and "1234" not in str(d)


def test_entry_funnel_attempts_total_includes_failed(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    monkeypatch.setattr(main, "strategy_scan_activity", lambda include_unwired=False: {"strategies": [
        {"strategy_tag": "t1", "categories": ["swing"], "status": "live_wired", "scans_today": 3, "successful_entries_today": 1}]})
    conn = main.get_db()
    main._log_real_attempt(conn, "AAA.NS", "B", "skipped_insufficient_real_qty", strategy="t1")
    main._log_real_attempt(conn, "BBB.NS", "B", "confirmed", strategy="t1")
    main._log_real_attempt(conn, "CCC.NS", "B", "rejected", strategy="t1")
    main._log_real_attempt(conn, "DDD.NS", "B", "error", strategy="t1")
    conn.close()
    sw = main.entry_funnel()["categories"]["swing"]
    assert (sw["placed"], sw["blocked"], sw["failed"]) == (1, 1, 2)
    assert sw["attempts_total"] == 4
    row = [r for r in sw["strategies"] if r["strategy"] == "t1"][0]
    assert (row["placed"], row["blocked"], row["failed"], row["attempts_total"]) == (1, 1, 2, 4)
