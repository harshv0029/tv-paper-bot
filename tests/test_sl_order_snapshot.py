"""B-71: latest SL/SL-M per tracked-union symbol per IST day, 5-day prune of
this table only. Run: pytest tests/test_sl_order_snapshot.py"""
import datetime as dt, json, os, tempfile, time
from contextlib import closing
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()
    main.UPSTASH_REDIS_REST_URL = ""


NOW = dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.timezone.utc)  # 15:30 IST, 2026-10-06


def test_captures_latest_sl_and_strips_account_keys():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO tracked_union (kotak_trading_symbol,qty,owner,updated_at) VALUES ('NYKAA-EQ',1,'swing',?)", (time.time(),))
        c.commit()
    rows = [
        {"trdSym": "NYKAA-EQ", "prcTp": "SL-M", "trgPrc": "330", "ordDtTm": "06-Oct-2026 10:00:00", "actId": "SECRET"},
        {"trdSym": "NYKAA-EQ", "prcTp": "SL", "trgPrc": "335", "ordDtTm": "06-Oct-2026 11:00:00"},
        {"trdSym": "NYKAA-EQ", "prcTp": "L", "ordDtTm": "06-Oct-2026 12:00:00"},
        {"trdSym": "OTHER-EQ", "prcTp": "SL", "ordDtTm": "06-Oct-2026 12:00:00"},
    ]
    assert main._sl_snapshot_capture(rows, NOW) == 1
    with closing(main.get_db()) as c:
        r = c.execute("SELECT * FROM sl_order_snapshot").fetchone()
    assert r["day"] == "2026-10-06" and r["sl_order_count"] == 2
    d = json.loads(r["latest_sl_json"])
    assert d["trgPrc"] == "335" and "actId" not in d


def test_prune_keeps_five_days_and_leaves_other_tables():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO tracked_union (kotak_trading_symbol,qty,owner,updated_at) VALUES ('A-EQ',1,'swing',?)", (time.time(),))
        for day in ("2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"):
            c.execute("INSERT INTO sl_order_snapshot (day,kotak_trading_symbol) VALUES (?, 'A-EQ')", (day,))
        c.commit()
    main._sl_snapshot_capture([], NOW)
    with closing(main.get_db()) as c:
        days = [r[0] for r in c.execute("SELECT day FROM sl_order_snapshot ORDER BY day")]
        assert days == ["2026-10-02", "2026-10-05"]  # keep 10-02..10-06 (5 days)
        assert c.execute("SELECT COUNT(*) FROM tracked_union").fetchone()[0] == 1


def test_empty_cycle_never_overwrites_earlier_capture():
    _db()
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO tracked_union (kotak_trading_symbol,qty,owner,updated_at) VALUES ('A-EQ',1,'swing',?)", (time.time(),))
        c.commit()
    main._sl_snapshot_capture([{"trdSym": "A-EQ", "prcTp": "SL", "trgPrc": "9", "ordDtTm": "06-Oct-2026 10:00:00"}], NOW)
    main._sl_snapshot_capture([], NOW)
    with closing(main.get_db()) as c:
        assert c.execute("SELECT COUNT(*) FROM sl_order_snapshot").fetchone()[0] == 1


def test_table_is_in_upstash_mirror():
    assert "sl_order_snapshot" in main._GENERIC_MIRROR_TABLES
