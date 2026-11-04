"""B-1461: running (mark-to-market) CAGR includes open holdings/positions at live prices."""
import datetime as dt
from pathlib import Path

import roc_kpis

SS = {"net_pnl_inr": 10.0, "covered_days": 10, "avg_deployed_inr": 1000.0, "reason": None}


def test_running_adds_unrealised_long_and_short():
    lots = [{"symbol": "A-EQ", "side": "long", "qty": 10, "entry_px": 100.0, "entry_value_inr": 1000.0, "seg": "nse_cm"},
            {"symbol": "B-EQ", "side": "short", "qty": 5, "entry_px": 200.0, "entry_value_inr": 1000.0, "seg": "nse_cm"}]
    r = roc_kpis.running_kpis(SS, lots, {"A-EQ": 105.0, "B-EQ": 190.0}, charges_fn=lambda *a: 1.0)
    assert r["unrealised_gross_inr"] == 100.0 and r["unrealised_charges_inr"] == 2.0
    assert r["total_net_inr"] == 108.0 and r["return_pct"] == 10.8
    assert r["cagr_pct"] == round((1.108 ** 36.5 - 1) * 100, 2)
    assert r["priced_lots"] == 2 and r["unpriced"] == []


def test_unpriced_lot_left_out_and_counted():
    lots = [{"symbol": "A-EQ", "side": "long", "qty": 10, "entry_px": 100.0, "entry_value_inr": 1000.0}]
    r = roc_kpis.running_kpis(SS, lots, {}, None)
    assert r["unpriced"] == ["A-EQ"] and r["total_net_inr"] == 10.0 and "no live price" in r["reason"]


def test_no_ledger_gives_none():
    r = roc_kpis.running_kpis({"net_pnl_inr": None, "covered_days": 0, "reason": "no Kotak fill ledger yet"}, [], {})
    assert r["cagr_pct"] is None and r["reason"] == "no Kotak fill ledger yet"


def test_open_lot_rows_carry_px_and_seg():
    rows = [{"day": "2026-11-02", "trdsym": "A-EQ", "prod": "CNC", "source": "kotak", "seg": "nse_cm",
             "buy_qty": 10, "buy_amt": 1000, "sell_qty": 0, "sell_amt": 0}]
    out = roc_kpis.roc_kpis(rows, dt.date(2026, 11, 4))
    o = out["open_lot_rows"][0]
    assert o["entry_px"] == 100.0 and o["seg"] == "nse_cm" and o["prod"] == "CNC"


def test_payload_has_running_block(monkeypatch):
    import main
    monkeypatch.setattr(main, "_open_positions_prices", lambda syms, wl, budget_s=None: {s: 1.0 for s in syms})
    main._roc_running_px_cache.update(at=0.0, px={}, syms=())
    out = main._roc_kpis_payload()
    assert "running" in out and "open_lot_rows" not in out
    assert out["running"].get("refresh_seconds") == 60


def test_view4_shows_running_cagr():
    h = (Path(__file__).resolve().parents[1] / "static" / "trade-view4.html").read_text()
    assert 'id="runLine"' in h and "Running CAGR" in h and "refreshed every" in h


def _union(monkeypatch, rows):
    import main
    import sqlite3

    def fake_db():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE tracked_union (kotak_trading_symbol TEXT, qty INTEGER, is_short INTEGER, entry_price REAL)")
        c.executemany("INSERT INTO tracked_union VALUES (?,?,?,?)", rows)
        return c
    monkeypatch.setattr(main, "get_db", fake_db)
    return main


def test_open_set_is_exactly_kotak_open(monkeypatch):
    main = _union(monkeypatch, [("A-EQ", 6, 0, 99.0), ("H-EQ", 4, 0, 50.0)])
    ledger = [{"symbol": "A-EQ", "side": "long", "qty": 10, "entry_px": 100.0, "entry_value_inr": 1000.0,
               "entry_day": "2026-11-02", "seg": "nse_cm", "prod": "CNC"},
              {"symbol": "GONE-EQ", "side": "long", "qty": 3, "entry_px": 10.0, "entry_value_inr": 30.0,
               "entry_day": "2026-11-02", "seg": "nse_cm", "prod": "CNC"}]
    out = main._roc_lots_matched_to_kotak(ledger, "2026-11-02")
    got = {(o["symbol"], o["qty"], o["entry_px"], o["source"]) for o in out}
    assert got == {("A-EQ", 6, 100.0, "kotak_fill"), ("H-EQ", 4.0, 50.0, "kotak_avg_price")}


def test_kotak_qty_above_ledger_fills_at_kotak_avg(monkeypatch):
    main = _union(monkeypatch, [("A-EQ", 12, 0, 99.0)])
    ledger = [{"symbol": "A-EQ", "side": "long", "qty": 10, "entry_px": 100.0, "entry_value_inr": 1000.0,
               "entry_day": "2026-11-02", "seg": "nse_cm", "prod": "CNC"}]
    out = main._roc_lots_matched_to_kotak(ledger, "2026-11-02")
    assert sorted((o["qty"], o["entry_px"]) for o in out) == [(2.0, 99.0), (10, 100.0)]
