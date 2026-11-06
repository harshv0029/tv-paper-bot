import sqlite3
import main


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE real_positions_swing (symbol TEXT, qty INT, entry_price REAL)")
    return c


def test_blocks_when_sector_over_cap(monkeypatch):
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {"A.NS": "Tech", "B.NS": "Tech", "C.NS": "Bank"})
    # B-1507: capital is Kotak's FREE Net; the account is free Net 80k + open swing cost 20k = 100k
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 80000.0)
    c = _conn()
    c.execute("INSERT INTO real_positions_swing VALUES ('A.NS', 10, 2000)")  # 20k = 20%
    assert main._sector_cap_blocks(c, "B.NS", 5, 2000) is not None   # +10k -> 30% > 25%
    assert main._sector_cap_blocks(c, "B.NS", 2, 2000) is None       # +4k -> 24%
    assert main._sector_cap_blocks(c, "C.NS", 20, 1000) is None      # other sector
    assert main._sector_cap_blocks(c, "ZZ.NS", 500, 1000) is None     # unknown sector -> allowed


def test_b1507_cap_is_share_of_whole_account_not_free_net(monkeypatch):
    """Live 2026-11-06 IST: free Net Rs5,904 -> old cap Rs1,476 blocked a Rs121 YESBANK buy 16x."""
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {"A.NS": "Fin", "Y.NS": "Fin"})
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 5904.53)
    c = _conn()
    c.execute("INSERT INTO real_positions_swing VALUES ('A.NS', 8, 134.39)")   # Rs1,075 open in Fin
    c.execute("INSERT INTO real_positions_swing VALUES ('B.NS', 2, 1100)")     # Rs2,200 open elsewhere
    assert main._sector_cap_blocks(c, "Y.NS", 7, 17.26) is None   # 1,196 <= 25% of 9,180 = 2,295
    assert main._sector_cap_blocks(c, "Y.NS", 100, 17.26) is not None   # 2,801 > 2,295
