import json, sqlite3, time
import main


def _db():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE real_positions_swing (symbol TEXT, opened_at REAL)")
    c.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, strategy TEXT, raw_payload TEXT)")
    c.execute("INSERT INTO real_positions_swing VALUES ('NYKAA.NS', 100)")
    return c


def test_no_paper_sell_means_no_retry_exit():
    assert main._swing_paper_exit_on_record(_db(), "NYKAA.NS") is None


def test_paper_sell_after_open_gives_its_reason():
    c = _db()
    c.execute("INSERT INTO trades VALUES (200,'NYKAA.NS','sell',?,?)",
              (main.SWING_STRATEGY_TAG, json.dumps({"exit_reason": "stop_hit"})))
    assert main._swing_paper_exit_on_record(c, "NYKAA.NS") == "stop_hit"


def test_paper_sell_before_open_is_ignored():
    c = _db()
    c.execute("INSERT INTO trades VALUES (50,'NYKAA.NS','sell',?,?)", (main.SWING_STRATEGY_TAG, "{}"))
    assert main._swing_paper_exit_on_record(c, "NYKAA.NS") is None
