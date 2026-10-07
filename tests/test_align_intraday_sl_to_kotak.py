"""B-295: Kotak-is-truth SL alignment for intraday long and short rows."""
from contextlib import closing
import main


def _o(oid, trg, side, st="trigger pending", sym="AAA-EQ"):
    return {"nOrdNo": oid, "trdSym": sym, "trnsTp": side, "prcTp": "SL", "ordSt": st, "trgPrc": str(trg)}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db")) if hasattr(main, "DB_PATH") else None
    main.init_db()
    monkeypatch.setattr(main, "_sync_real_positions_external", lambda c: None)
    monkeypatch.setattr(main, "_sync_real_positions_short_external", lambda c: None)
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: None)


def _ins(conn, table, sym, tsym, oid, trg):
    cols = "symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, sl_order_id, sl_trigger_price"
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES (?,?,?,?,?,?,?,?)",
                 (sym, tsym, 1, 100.0, 0.0, "2026-10-07", oid, trg))


def test_long_and_short_adopt_and_conservative_clear(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with closing(main.get_db()) as conn:
        conn.execute("DELETE FROM real_positions"); conn.execute("DELETE FROM real_positions_short")
        _ins(conn, "real_positions", "AAA.NS", "AAA-EQ", "OLD", 90.0)          # Kotak has a different live SL
        _ins(conn, "real_positions", "BBB.NS", "BBB-EQ", "DEAD", 80.0)         # Kotak lists it rejected -> clear
        _ins(conn, "real_positions", "CCC.NS", "CCC-EQ", "LAG", 70.0)          # absent from book -> keep
        _ins(conn, "real_positions_short", "DDD.NS", "DDD-EQ", None, None)     # Kotak has live BUY SL -> adopt
        conn.commit()
        rows = [_o("NEW", 95.5, "S", sym="AAA-EQ"), _o("DEAD", 80, "S", st="rejected", sym="BBB-EQ"),
                _o("S1", 110.0, "B", sym="DDD-EQ"), _o("S2", 108.0, "B", sym="DDD-EQ")]
        out = main._align_intraday_sl_rows_to_kotak(conn, rows)
        g = lambda t, s: conn.execute(f"SELECT sl_order_id, sl_trigger_price FROM {t} WHERE symbol=?", (s,)).fetchone()
        assert tuple(g("real_positions", "AAA.NS")) == ("NEW", 95.5)
        assert g("real_positions", "BBB.NS")[0] is None
        assert g("real_positions", "CCC.NS")[0] == "LAG"
        assert tuple(g("real_positions_short", "DDD.NS")) == ("S2", 108.0)  # tighter (lower) BUY stop wins
        assert len(out) == 3
        assert main._align_intraday_sl_rows_to_kotak(conn, []) == []
