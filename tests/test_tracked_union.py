"""Tracked union (positions + holdings): persist, owner memory, swing-row
restore after a wipe, prune, git-journal fallback. Run: pytest tests/test_tracked_union.py"""
import json, os, tempfile, time
from contextlib import closing
import main


def _db():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()


def _swing(conn):
    conn.execute("INSERT INTO real_positions_swing (symbol,kotak_trading_symbol,qty,entry_price,opened_at,day,stop_loss,strategy)"
                 " VALUES ('NYKAA.NS','NYKAA-EQ',1,340.11,?, '2026-10-05',335.0,'gap_and_go')", (time.time(),))
    conn.commit()


def test_union_of_positions_and_holdings_and_prune():
    _db()
    pos = {"RVNL-EQ": {"qty": 2, "is_short": False, "raw": {}}}
    hold = {"NYKAA-EQ": {"qty": 1, "avg_price": 340.11, "symbol": "NYKAA"}}
    with closing(main.get_db()) as c:
        main._tracked_union_persist(c, pos, hold)
        assert {r[0] for r in c.execute("SELECT kotak_trading_symbol FROM tracked_union")} == {"RVNL-EQ", "NYKAA-EQ"}
        main._tracked_union_persist(c, {}, hold)  # RVNL flat -> pruned
        assert c.execute("SELECT COUNT(*) FROM tracked_union").fetchone()[0] == 1
        main._tracked_union_persist(c, {}, None)  # holdings fetch failed -> never prune
        assert c.execute("SELECT COUNT(*) FROM tracked_union").fetchone()[0] == 1


def test_lost_swing_row_is_restored_not_misadopted():
    _db()
    hold = {"NYKAA-EQ": {"qty": 1, "avg_price": 340.11, "symbol": "NYKAA"}}
    with closing(main.get_db()) as c:
        _swing(c)
        main._tracked_union_persist(c, {}, hold)
        c.execute("DELETE FROM real_positions_swing"); c.commit()  # restart amnesia
        restored = main._tracked_union_persist(c, {}, hold)
        assert restored == ["NYKAA-EQ"]
        r = c.execute("SELECT stop_loss, strategy FROM real_positions_swing WHERE symbol='NYKAA.NS'").fetchone()
        assert r["stop_loss"] == 335.0 and r["strategy"] == "gap_and_go"


def test_journal_fallback_restores_missing_rows(tmp_path):
    _db()
    f = tmp_path / "u.json"
    f.write_text(json.dumps({"rows": [{"kotak_trading_symbol": "INDHOTEL-EQ", "symbol": "INDHOTEL.NS",
                                       "qty": 1, "owner": "swing", "is_short": 0}]}))
    main._TRACKED_UNION_JOURNAL = str(f)
    assert main.reconcile_tracked_union_from_journal() == 1
    assert main.reconcile_tracked_union_from_journal() == 0


def test_in_mirror_list():
    assert "tracked_union" in main._GENERIC_MIRROR_TABLES
