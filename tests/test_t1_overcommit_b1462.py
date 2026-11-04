"""B-1462: an over-committed duplicate sell (Used > Available, Available > 0) is not a T1/T2T restriction."""
import sqlite3

import main

OVER = ("RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,Used:16.00, Available:8.00  for entity account-X "
        "across exchange across segment across product ")
REAL_T1 = "RMS:Rule: Check T1 holdings including TT/BE/Z/T/TS ,No Holdings Present for entity account-X"


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE real_t1_restricted (symbol TEXT, day TEXT, flagged_at REAL, detail TEXT, "
              "PRIMARY KEY (symbol, day))")
    return c


def test_overcommit_detected():
    assert main._is_sell_overcommit_rejection(OVER)
    assert not main._is_sell_overcommit_rejection(REAL_T1)
    assert not main._is_sell_overcommit_rejection("RMS:Rule: Check T1 holdings ,Used:8.00, Available:0.00")
    assert not main._is_sell_overcommit_rejection(None)


def test_overcommit_not_flagged(monkeypatch):
    monkeypatch.setattr(main, "_sync_t1_restricted_external", lambda c: None)
    c = _conn()
    main._flag_if_t1_restricted(c, "BANKINDIA.NS", OVER)
    assert not main._is_t1_restricted(c, "BANKINDIA.NS")
    main._flag_if_t1_restricted(c, "AGL.NS", REAL_T1)
    assert main._is_t1_restricted(c, "AGL.NS")


def test_old_overcommit_row_ignored():
    c = _conn()
    c.execute("INSERT INTO real_t1_restricted VALUES ('BANKINDIA.NS', '2026-11-04', 0, ?)", (OVER,))
    assert not main._is_t1_restricted(c, "BANKINDIA.NS")
    c.execute("INSERT INTO real_t1_restricted VALUES ('BANKINDIA.NS', '2026-09-01', 0, ?)", (REAL_T1,))
    assert main._is_t1_restricted(c, "BANKINDIA.NS")
