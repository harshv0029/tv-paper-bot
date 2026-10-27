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


def test_entry_funnel_attempts_equal_placed_blocked_failed_and_skip_exits(monkeypatch):
    """B-1285: per-tag 'attempts' == placed + blocked + failed; exit/cover rows and untagged order rows are not attempts."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    short_tag = "x__v__short__15m__atr4d0__v1"
    monkeypatch.setattr(main, "strategy_scan_activity", lambda include_unwired=False: {"strategies": [
        {"strategy_tag": "t1", "categories": ["swing"], "status": "live_wired", "scans_today": 3, "successful_entries_today": 1},
        {"strategy_tag": short_tag, "categories": ["short_sell"], "status": "live_wired",
         "scans_today": 2, "successful_entries_today": 1}]})
    conn = main.get_db()
    main._log_real_attempt(conn, "AAA.NS", "B", "skipped_insufficient_real_qty", strategy="t1")
    main._log_real_attempt(conn, "BBB.NS", "B", "confirmed", strategy="t1")
    main._log_real_attempt(conn, "CCC.NS", "B", "failed", strategy="t1")
    main._log_real_attempt(conn, "BBB.NS", "S", "confirmed", strategy="t1")  # swing exit sell
    main._log_real_attempt(conn, "DDD.NS", "S", "failed", strategy="t1")  # failed swing exit
    main._log_real_attempt(conn, "EEE.NS", "S", "confirmed", strategy=short_tag)
    main._log_real_attempt(conn, "EEE.NS", "B", "confirmed", strategy=short_tag)  # cover
    main._log_real_attempt(conn, "FFF.NS", "S", "confirmed")  # untagged intraday long exit
    main._log_real_attempt(conn, "__reconciled__", "B", "confirmed")
    conn.close()
    d = main.entry_funnel()["categories"]
    sw = d["swing"]
    row = [r for r in sw["strategies"] if r["strategy"] == "t1"][0]
    assert (row["placed"], row["blocked"], row["failed"], row["attempts"], row["attempts_total"]) == (1, 1, 1, 3, 3)
    assert (sw["placed"], sw["blocked"], sw["failed"], sw["attempts_total"]) == (1, 1, 1, 3)
    ss = d["short_sell"]
    srow = [r for r in ss["strategies"] if r["strategy"] == short_tag][0]
    assert (srow["placed"], srow["failed"], srow["attempts"]) == (1, 0, 1)
    assert ss["attempts_total"] == 1 and "None" not in [r["strategy"] for r in ss["strategies"]]
    assert d["buy"]["attempts_total"] == 0 and d["buy"]["failed"] == 0
