import sqlite3
import time

import main
import rolling_monitor as rm


def test_rolling_monitor():
    assert rm.should_alert([1] * 5)[0] is False
    assert rm.should_alert([-1] * 20)[0] is True
    assert rm.should_alert([5, -1] * 10)[0] is False
    assert rm.should_alert([1, -2] * 10)[0] is True
    assert rm.rolling_stats([3, -1])["pfnet"] == 3.0


def test_sl_loosen_detection():
    assert main._sl_would_loosen(False, 99, 100) is True
    assert main._sl_would_loosen(False, 100, 100) is False
    assert main._sl_would_loosen(False, 101, 100) is False
    assert main._sl_would_loosen(True, 101, 100) is True
    assert main._sl_would_loosen(True, 99, 100) is False
    main._SL_LOOSEN_ATTEMPTS.clear()
    assert main._note_sl_loosen_attempt("X", True, 105, 100)
    assert main._SL_LOOSEN_ATTEMPTS == {"short": 1}


def test_swing_time_limit():
    now = time.time()
    rows = [{"symbol": "A", "strategy": "gap_and_go", "opened_at": now - 80 * 86400},
            {"symbol": "B", "strategy": "gap_and_go", "opened_at": now - 5 * 86400}]
    out = main._find_swing_positions_past_time_limit(rows, now)
    assert [r["symbol"] for r in out] == ["A"]


def test_shadow_log_and_mirror():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE signal_shadow_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, strategy_tag TEXT, symbol TEXT, direction TEXT, taken INTEGER, reason TEXT, hard_gate INTEGER DEFAULT 0)")
    main._log_signal_shadow(c, "t", "S.NS", "long", False, "why", hard_gate=True)
    r = c.execute("SELECT taken, hard_gate, reason FROM signal_shadow_log").fetchone()
    assert tuple(r) == (0, 1, "why")
    assert "signal_shadow_log" in main._GENERIC_MIRROR_TABLES
