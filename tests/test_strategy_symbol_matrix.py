"""Tests for GET /strategy-symbol-matrix and the /trade-view2, /trade-view3 pages."""
import json
import os
import tempfile
import time
from contextlib import closing

from fastapi.testclient import TestClient

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _reset():
    main._pair_scan_stats.clear()
    main._pair_scan_day = ""
    main._symbol_strategy_scans.clear()
    main._symbol_strategy_scans_day = ""
    main._strategy_scan_counts.clear()
    main._strategy_scan_counts_day = ""
    main._SCAN_ACTIVITY_CACHE.clear()
    main._MATRIX_CACHE[1] = None


def test_pair_scan_recorded_via_symbol_scan_and_windows():
    _reset()
    tok = main._current_scan_symbol.set("AAA.NS")
    try:
        main._record_symbol_strategy_scan("tagx")
        main._record_symbol_strategy_scan("tagx")
    finally:
        main._current_scan_symbol.reset(tok)
    rec = main._pair_scan_stats[("tagx", "AAA.NS")]
    assert rec[0] == 2 and len(rec[1]) == 2


def test_pair_scan_deque_is_bounded():
    _reset()
    for _ in range(main._PAIR_SCAN_RECENT_MAX + 50):
        main._record_pair_scan("t", "S", "2026-10-20")
    assert len(main._pair_scan_stats[("t", "S")][1]) == main._PAIR_SCAN_RECENT_MAX


def test_matrix_rows_entries_and_pct(monkeypatch):
    _reset()
    _fresh_db()
    tag = next(t for t in main._STRATEGY_TAG_TO_REGISTRY_NAME if main._is_strategy_viable_for_real_money(t))
    now = time.time()
    with closing(main.get_db()) as c:
        for ts, act, px in ((now - 100, "buy", 100.0), (now - 50, "sell", 110.0)):
            c.execute("INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                      (ts, "ZZZ.NS", act, 1, px, 1.0, tag, json.dumps({"entry_reason": tag})))
        c.commit()
    tok = main._current_scan_symbol.set("ZZZ.NS")
    try:
        main._record_symbol_strategy_scan(tag)
    finally:
        main._current_scan_symbol.reset(tok)
    out = main._strategy_symbol_matrix_compute()
    rows = [r for r in out["by_symbol"] if r["strategy"] == tag and r["symbol"] == "ZZZ.NS"]
    assert rows
    r = rows[0]
    assert r["entries_today"] == 1 and r["entries_total"] == 1
    assert r["pct_profitable"] == 100.0
    assert r["scans_today"] == 1 and r["scans_30s"] == 1 and r["scans_1h"] == 1
    srows = [x for x in out["by_strategy"] if x["strategy"] == tag]
    assert srows and "ZZZ.NS" in srows[0]["symbols"] and srows[0]["sr"] >= 1


def test_endpoint_and_pages():
    _reset()
    _fresh_db()
    cl = TestClient(main.app)
    j = cl.get("/strategy-symbol-matrix").json()
    assert {"by_strategy", "by_symbol", "notes"} <= set(j)
    for p in ("/trade-view2", "/trade-view3"):
        r = cl.get(p)
        assert r.status_code == 200 and "strategy-symbol-matrix" in r.text
