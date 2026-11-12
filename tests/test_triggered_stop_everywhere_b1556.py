"""B-1556: a stop that TRIGGERED at Kotak stays working with prcTp L (not SL) but keeps its trigger price. Every order-book
scan that decides protection must read it as an exit in progress, never as 'unprotected' (which draws a second exit)."""
from contextlib import closing
from types import SimpleNamespace

import pytest

import kotak_real_orders as k
import main


def _trig(side="S", st="open", sym="COCHINSHIP-EQ", oid="77"):
    return {"nOrdNo": oid, "trdSym": sym, "trnsTp": side, "prcTp": "L", "ordSt": st, "trgPrc": "1203.70", "qty": "1"}


def _target(side="S", sym="COCHINSHIP-EQ"):
    return {"nOrdNo": "88", "trdSym": sym, "trnsTp": side, "prcTp": "L", "ordSt": "open", "trgPrc": "0.00", "qty": "1"}


def test_predicate():
    assert k.is_triggered_stop_row(_trig(), "S")
    assert not k.is_triggered_stop_row(_trig(), "B")
    assert not k.is_triggered_stop_row(_target(), "S")             # a plain target limit is not protection
    assert not k.is_triggered_stop_row(_trig(st="complete"), "S")
    assert not k.is_triggered_stop_row(dict(_trig(), prcTp="SL"), "S")  # resting stops are read by the usual check


@pytest.mark.parametrize("short", [False, True])
def test_backcheck_counts_a_triggered_stop_as_protection(short):
    side = "B" if short else "S"
    pos = {"COCHINSHIP-EQ": {"qty": 1, "is_short": short}}
    assert main._find_unprotected_open_positions(pos, [_trig(side)]) == []
    assert main._find_unprotected_open_positions(pos, [_target(side)]) != []


def test_holding_heal_places_nothing_on_a_triggered_stop():
    r = main._heal_swing_holding_core("COCHINSHIP-EQ", {"avg_price": 1240.0, "qty": 1}, [_trig()])
    assert r["status"].startswith("already_protected")


def _fake_book(monkeypatch, rows):
    monkeypatch.setattr(k.kotak_neo, "login", lambda: SimpleNamespace(order_report=lambda: {"data": rows}))
    placed = []
    monkeypatch.setattr(k, "place_real_stop_loss", lambda *a, **kw: placed.append(a) or {"ok": True})
    monkeypatch.setattr(k, "_place_real_stop_loss_once", lambda *a, **kw: placed.append(a) or {"ok": True})
    return placed


def test_ensure_resting_sl_never_stacks_on_a_triggered_stop(monkeypatch):
    placed = _fake_book(monkeypatch, [_trig()])
    monkeypatch.setattr(k, "_exchange_purge_window", lambda *a, **kw: False, raising=False)
    r = k.ensure_resting_sl("COCHINSHIP-EQ", 1, 1250.0)
    assert r["ok"] and r["action"] == "stop_triggered_exit_working" and r["order_id"] == "77" and placed == []


@pytest.mark.parametrize("fn,side", [("cancel_existing_resting_sl", "S"), ("cancel_existing_resting_sl_short", "B")])
def test_cancel_before_exit_also_cancels_a_triggered_stop(monkeypatch, fn, side):
    monkeypatch.setattr(k.kotak_neo, "login",
                        lambda: SimpleNamespace(order_report=lambda: {"data": [_trig(side), _target(side)]}))
    cancelled = []
    monkeypatch.setattr(k, "cancel_real_order", lambda oid: cancelled.append(oid) or {"ok": True})
    out = getattr(k, fn)("COCHINSHIP-EQ")
    assert out["cancelled"] == ["77"] and cancelled == ["77"]   # the target is left to its own exit path


def test_short_ensure_never_stacks_on_a_triggered_buy_stop(monkeypatch):
    import kotak_neo
    monkeypatch.setattr(kotak_neo, "order_report", lambda: {"data": [_trig("B")]})
    placed = []
    monkeypatch.setattr(k, "place_real_short_stop_loss", lambda *a, **kw: placed.append(a) or {"ok": True})
    r = main._ensure_resting_short_sl("COCHINSHIP-EQ", 1, 1300.0)
    assert r["ok"] and r["action"] == "stop_triggered_exit_working" and placed == []


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: False)
    return tmp_path


def test_swing_short_heal_keeps_the_id_of_a_triggered_buy_stop(db):
    with closing(main.get_db()) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(real_positions_swing_short)")]
        vals = {"symbol": "X.NS", "kotak_trading_symbol": "COCHINSHIP-EQ", "qty": 1, "entry_price": 1250.0,
                "stop_loss": 1300.0, "sl_order_id": "77", "sl_trigger_price": 1203.7, "day": "2026-11-11",
                "opened_at": 0, "strategy": "s"}
        vals = {kk: v for kk, v in vals.items() if kk in cols}
        c.execute(f"INSERT INTO real_positions_swing_short ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                  tuple(vals.values()))
        c.commit()
        main._heal_real_swing_short_sl(c, [_trig("B")])
        assert c.execute("SELECT sl_order_id FROM real_positions_swing_short").fetchone()[0] == "77"
