"""B-1601: the same skipped signal re-checked every scan pass is logged once per day."""
import sqlite3
import main


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE signal_shadow_log (id INTEGER PRIMARY KEY, ts REAL, day TEXT, strategy_tag TEXT, "
              "symbol TEXT, direction TEXT, taken INTEGER, reason TEXT, hard_gate INTEGER)")
    return c


def test_repeat_logged_once_but_new_reason_or_taken_still_logged():
    c = _conn()
    for _ in range(5):
        main._log_signal_shadow(c, "t__v1", "ABC.NS", "long", False, "real entry: strategy below PFnet floor", True)
    assert c.execute("SELECT COUNT(*) FROM signal_shadow_log").fetchone()[0] == 1
    main._log_signal_shadow(c, "t__v1", "ABC.NS", "long", False, "option leg: strategy below PFnet floor", True)
    main._log_signal_shadow(c, "t__v1", "ABC.NS", "long", True, "real swing entry placed")
    main._log_signal_shadow(c, "t__v1", "XYZ.NS", "long", False, "real entry: strategy below PFnet floor", True)
    assert c.execute("SELECT COUNT(*) FROM signal_shadow_log").fetchone()[0] == 4
