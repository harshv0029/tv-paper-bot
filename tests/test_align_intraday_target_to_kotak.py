"""B-295 part 3: Kotak-is-truth target order alignment for intraday long rows."""
from contextlib import closing
import main


def _o(oid, prc, st="open", sym="AAA-EQ", side="S", pt="L"):
    return {"nOrdNo": oid, "trdSym": sym, "trnsTp": side, "prcTp": pt, "ordSt": st, "prc": str(prc)}


def test_target_adopt_clear_keep(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db")) if hasattr(main, "DB_PATH") else None
    main.init_db()
    monkeypatch.setattr(main, "_sync_real_positions_external", lambda c: None)
    monkeypatch.setattr(main, "_log_real_order_event", lambda *a, **k: None)
    cols = "symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, target_order_id, target_price"
    with closing(main.get_db()) as conn:
        conn.execute("DELETE FROM real_positions")
        for sym, ts, oid, px in (("AAA.NS", "AAA-EQ", "OLD", 150.0), ("BBB.NS", "BBB-EQ", "DEAD", 160.0),
                                 ("CCC.NS", "CCC-EQ", "LAG", 170.0), ("DDD.NS", "DDD-EQ", None, None)):
            conn.execute(f"INSERT INTO real_positions ({cols}) VALUES (?,?,?,?,?,?,?,?)",
                         (sym, ts, 1, 100.0, 0.0, "2026-10-07", oid, px))
        conn.commit()
        rows = [_o("NEW", 155.5), _o("DEAD", 160, st="cancelled", sym="BBB-EQ"),
                _o("T1", 120, sym="DDD-EQ"), _o("T2", 118, sym="DDD-EQ"),
                _o("SLX", 90, sym="DDD-EQ", pt="SL")]
        out = main._align_intraday_target_to_kotak(conn, rows)
        g = lambda s: tuple(conn.execute("SELECT target_order_id, target_price FROM real_positions WHERE symbol=?", (s,)).fetchone())
        assert g("AAA.NS") == ("NEW", 155.5)
        assert g("BBB.NS")[0] is None
        assert g("CCC.NS")[0] == "LAG"
        assert g("DDD.NS") == ("T2", 118.0)
        assert len(out) == 3
        assert main._align_intraday_target_to_kotak(conn, []) == []
