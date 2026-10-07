"""ensure_resting_sl (2026-10-07): scan Kotak's order book before any swing SL action."""
import kotak_real_orders as kro


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def order_report(self):
        return {"data": self.rows}


def _row(oid, trg, qty=1, st="trigger pending", sym="DRREDDY-EQ"):
    return {"nOrdNo": oid, "trdSym": sym, "trnsTp": "S", "prcTp": "SL", "ordSt": st,
            "trgPrc": str(trg), "qty": str(qty)}


def _patch(monkeypatch, rows, place_results):
    placed, cancelled = [], []
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _Client(rows))
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: cancelled.append(oid) or {"ok": True})
    results = list(place_results)

    def fake_place(sym, qty, trg):
        placed.append(trg)
        return results.pop(0) if results else {"ok": True, "order_id": "NEW", "trigger_price": trg}
    monkeypatch.setattr(kro, "place_real_stop_loss", fake_place)
    return placed, cancelled


def test_adopts_existing_when_trigger_already_high_enough(monkeypatch):
    placed, cancelled = _patch(monkeypatch, [_row("A", 1172.6)], [])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1172.6)
    assert r["ok"] and r["action"] == "adopted_existing" and r["order_id"] == "A"
    assert placed == [] and cancelled == []


def test_never_lowers_an_existing_stop(monkeypatch):
    placed, cancelled = _patch(monkeypatch, [_row("A", 1172.6)], [])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1100.0)
    assert r["action"] == "adopted_existing" and placed == [] and cancelled == []


def test_ratchet_cancels_old_then_places_new(monkeypatch):
    placed, cancelled = _patch(monkeypatch, [_row("A", 1172.6)], [])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1193.3)
    assert r["ok"] and r["action"] == "replaced" and cancelled == ["A"] and placed == [1193.3]


def test_failed_replace_restores_old_stop(monkeypatch):
    placed, cancelled = _patch(
        monkeypatch, [_row("A", 1172.6)],
        [{"ok": False, "detail": "rejected"}, {"ok": True, "order_id": "R", "trigger_price": 1172.6}])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1193.3)
    assert not r["ok"] and r["action"] == "replace_failed"
    assert r["restored_order_id"] == "R" and placed == [1193.3, 1172.6]


def test_terminal_orders_ignored_and_fresh_place(monkeypatch):
    placed, cancelled = _patch(monkeypatch, [_row("A", 1172.6, st="rejected")], [])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1172.6)
    assert r["action"] == "placed" and placed == [1172.6] and cancelled == []


def test_other_symbols_ignored(monkeypatch):
    placed, cancelled = _patch(monkeypatch, [_row("A", 999, sym="RVNL-EQ")], [])
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1172.6)
    assert r["action"] == "placed" and cancelled == []


def test_unreadable_order_book_falls_back_to_plain_place(monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(kro.kotak_neo, "login", boom)
    monkeypatch.setattr(kro, "place_real_stop_loss", lambda s, q, t: {"ok": True, "order_id": "N", "trigger_price": t})
    r = kro.ensure_resting_sl("DRREDDY-EQ", 1, 1172.6)
    assert r["ok"] and r["action"] == "placed_unchecked"


def test_align_swing_rows_to_kotak(tmp_path, monkeypatch):
    import main
    from contextlib import closing
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db")) if hasattr(main, "DB_PATH") else None
    main.init_db()
    with closing(main.get_db()) as conn:
        conn.execute("DELETE FROM real_positions_swing")
        for sym, oid, trg in (("AAA.NS", "OLD", 100.0), ("BBB.NS", "GONE", 50.0), ("CCC.NS", None, None)):
            conn.execute(
                "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, stop_loss, strategy, sl_order_id, sl_trigger_price) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sym, sym[:3] + "-EQ", 1, 100.0, 0.0, "2026-10-07", 90.0, "gap_and_go", oid, trg))
        conn.commit()
        rows = [_row("NEW", 105.5, sym="AAA-EQ"), _row("X", 1, st="rejected", sym="BBB-EQ"), _row("CK", 77.0, sym="CCC-EQ")]
        monkeypatch.setattr(main, "_sync_real_positions_swing_external", lambda c: None)
        out = main._align_swing_sl_rows_to_kotak(conn, rows)
        got = {r["symbol"]: (r["sl_order_id"], r["sl_trigger_price"]) for r in conn.execute("SELECT * FROM real_positions_swing")}
        assert got["AAA.NS"] == ("NEW", 105.5)
        assert got["BBB.NS"][0] is None
        assert got["CCC.NS"] == ("CK", 77.0)
        assert {a["action"] for a in out} == {"aligned_to_kotak", "cleared_no_live_sl_at_kotak"}
        assert main._align_swing_sl_rows_to_kotak(conn, []) == []  # unreadable book changes nothing
