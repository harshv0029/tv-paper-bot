"""B-1517: the swing sector cap charges the REAL qty x live price, checked after real sizing (not paper qty)."""
import inspect
import main


def test_sector_cap_uses_real_qty_after_sizing():
    src = inspect.getsource(main._maybe_place_real_swing_entry)
    assert "_sector_cap_blocks(conn, symbol, paper_qty" not in src
    assert "_sector_cap_blocks(conn, symbol, qty, ltp)" in src
    assert src.index("risk_qty = _real_swing_qty_by_risk") < src.index("_sector_cap_blocks(conn, symbol, qty, ltp)")


def test_one_share_bosch_not_blocked(monkeypatch):
    # 1 share at Rs40k is still measured as Rs40k; a paper qty of 10 must no longer be what is charged.
    import sqlite3
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE real_positions_swing (symbol TEXT, qty REAL, entry_price REAL)")
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {"X.NS": "Auto"})
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 200000.0)
    assert main._sector_cap_blocks(conn, "X.NS", 1, 40000.0) is None
    assert main._sector_cap_blocks(conn, "X.NS", 10, 40000.0)
