"""B-1637: every real swing long has a time exit (default backstop), and the manual exit sells the breach-exit way."""
import datetime as dt
from contextlib import closing

import pytest

import main


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    with closing(main.get_db()) as c:
        yield c


def _add(c, sym, strategy, day, qty=5):
    c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
              "stop_loss, sl_order_id, strategy) VALUES (?,?,?,?,?,?,?,?,?)",
              (sym, sym.replace(".NS", "-EQ"), qty, 100.0, 1.0, day, 90.0, "SL1", strategy))
    c.commit()
    return c.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", (sym,)).fetchone()


def test_expected_exit_never_blank_for_adopted_holding():
    r = main._expected_exit_for_position("swing", "holding_atr_stop", "2026-11-17")
    assert r["expected_exit"] and "immediate" in r["expected_exit_basis"]


def test_time_exit_due_rules(db):
    adopted = _add(db, "AAA.NS", "holding_atr_stop", "2026-08-01")
    due, exp, _ = main._swing_time_exit_due(adopted, dt.date(2026, 11, 19))
    assert due and exp
    own = _add(db, "BBB.NS", "order_block_delta", "2026-10-08")
    exp_own = main._expected_exit_for_position("swing", "order_block_delta", "2026-10-08")["expected_exit"]
    d = dt.date.fromisoformat(exp_own)
    assert main._swing_time_exit_due(own, d)[0] is False  # own engine exits on the day itself
    assert main._swing_time_exit_due(own, d + dt.timedelta(days=1))[0] is True  # backstop the day after
    fresh = _add(db, "CCC.NS", "holding_atr_stop", "2026-11-17")
    assert main._swing_time_exit_due(fresh, dt.date(2026, 11, 19))[0] is True  # no time stop -> immediate


def _in_session(monkeypatch, book=None):
    import kotak_neo
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(2026, 11, 19, 11, 0))
    monkeypatch.setattr(main, "_nse_closed_day", lambda n: False)
    monkeypatch.setattr(kotak_neo, "order_report", lambda *a, **k: {"data": book or []})


def test_market_exit_cancels_then_sells_held_qty(db, monkeypatch):
    import kotak_real_orders as kro
    _in_session(monkeypatch)
    _add(db, "AAA.NS", "holding_atr_stop", "2026-11-17", qty=5)
    calls = []
    monkeypatch.setattr(main, "_kotak_holdings_open_by_trdsym", lambda: {"AAA-EQ": {"qty": 7, "avg_price": 100}})
    monkeypatch.setattr(kro, "cancel_all_open_sells", lambda t: calls.append(("cxl", t)) or {"ok": True, "cancelled": ["SL1"]})
    monkeypatch.setattr(main, "_kotak_swing_symbol_still_held", lambda t: True)
    monkeypatch.setattr(kro, "place_real_exit", lambda t, q, **k: calls.append(("sell", t, q)) or {
        "ok": True, "qty": q, "fill_price": 101.0, "fill_price_confirmed": True, "order_id": "X1", "raw_response": None})
    out = main._swing_market_exit_now(db, "AAA.NS", "manual_exit: test")
    assert out["status"] == "sold"
    assert calls == [("cxl", "AAA-EQ"), ("sell", "AAA-EQ", 7)]  # cancel first, Kotak's held qty wins


def test_market_exit_no_sell_when_cancel_fails(db, monkeypatch):
    import kotak_real_orders as kro
    _in_session(monkeypatch)
    _add(db, "AAA.NS", "holding_atr_stop", "2026-11-17")
    sold = []
    monkeypatch.setattr(main, "_kotak_holdings_open_by_trdsym", lambda: {"AAA-EQ": {"qty": 5}})
    monkeypatch.setattr(kro, "cancel_all_open_sells", lambda t: {"ok": False})
    monkeypatch.setattr(kro, "place_real_exit", lambda *a, **k: sold.append(a))
    assert main._swing_market_exit_now(db, "AAA.NS", "x")["status"] == "deferred_cancel_pending"
    assert sold == []


def test_market_exit_outside_session_deferred(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(2026, 11, 19, 15, 20))
    monkeypatch.setattr(main, "_nse_closed_day", lambda n: False)
    _add(db, "AAA.NS", "holding_atr_stop", "2026-11-17")
    assert main._swing_market_exit_now(db, "AAA.NS", "x")["status"] == "deferred_outside_session"


def test_sweep_exits_only_due_rows(db, monkeypatch):
    _in_session(monkeypatch)
    _add(db, "ADOPT.NS", "holding_atr_stop", "2026-11-17")
    _add(db, "OWN.NS", "order_block_delta", "2026-11-18")  # dated, not due: its own process is kept
    hit = []
    monkeypatch.setattr(main, "_swing_market_exit_now", lambda c, s, why: hit.append((s, why)) or {"symbol": s})
    main._swing_time_exit_sweep(db)
    assert [h[0] for h in hit] == ["ADOPT.NS"] and hit[0][1].startswith("time_exit_backstop")


def test_endpoint_requires_token_and_symbols(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main, "_require_kotak_token", lambda r: None)
    with pytest.raises(HTTPException):
        main.kotak_neo_exit_swing_holding(None, symbols=" , ")


def test_market_exit_never_resells_shares_sold_today(db, monkeypatch):
    """B-1638 (19-Nov CANBK race): holdings() still lists shares sold today until T+1. A complete delivery sell in
    the fresh order book that covers the holding closes the row and sends nothing."""
    import kotak_real_orders as kro
    _in_session(monkeypatch, book=[{"trdSym": "AAA-EQ", "trnsTp": "S", "ordSt": "complete", "prod": "CNC",
                                    "fldQty": 2, "qty": 2, "prcTp": "MKT"}])
    _add(db, "AAA.NS", "holding_atr_stop", "2026-11-17", qty=2)
    sent = []
    monkeypatch.setattr(main, "_kotak_holdings_open_by_trdsym", lambda: {"AAA-EQ": {"qty": 2, "avg_price": 100}})
    monkeypatch.setattr(kro, "cancel_all_open_sells", lambda t: sent.append(("cxl", t)) or {"ok": True})
    monkeypatch.setattr(kro, "place_real_exit", lambda *a, **k: sent.append(("sell", a)))
    out = main._swing_market_exit_now(db, "AAA.NS", "time_exit_backstop: test")
    assert out["status"] == "already_sold_today" and sent == []
    assert db.execute("SELECT 1 FROM real_positions_swing WHERE symbol='AAA.NS'").fetchone() is None


def test_market_exit_defers_when_book_unreadable(db, monkeypatch):
    import kotak_neo
    import kotak_real_orders as kro
    _in_session(monkeypatch)
    monkeypatch.setattr(kotak_neo, "order_report", lambda *a, **k: {"error": "down"})
    _add(db, "AAA.NS", "holding_atr_stop", "2026-11-17", qty=2)
    sent = []
    monkeypatch.setattr(main, "_kotak_holdings_open_by_trdsym", lambda: {"AAA-EQ": {"qty": 2}})
    monkeypatch.setattr(kro, "cancel_all_open_sells", lambda t: sent.append(t) or {"ok": True})
    assert main._swing_market_exit_now(db, "AAA.NS", "x")["status"] == "deferred_book_unreadable" and sent == []
