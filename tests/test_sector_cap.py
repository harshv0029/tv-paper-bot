import sqlite3
import main


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE real_positions_swing (symbol TEXT, qty INT, entry_price REAL)")
    return c


def test_blocks_when_sector_over_cap(monkeypatch):
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {"A.NS": "Tech", "B.NS": "Tech", "C.NS": "Bank"})
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 100000.0)
    c = _conn()
    c.execute("INSERT INTO real_positions_swing VALUES ('A.NS', 10, 2000)")  # 20k = 20%
    assert main._sector_cap_blocks(c, "B.NS", 5, 2000) is not None   # +10k -> 30% > 25%
    assert main._sector_cap_blocks(c, "B.NS", 2, 2000) is None       # +4k -> 24%
    assert main._sector_cap_blocks(c, "C.NS", 20, 1000) is None      # other sector
    assert main._sector_cap_blocks(c, "ZZ.NS", 500, 1000) is None     # unknown sector -> allowed
