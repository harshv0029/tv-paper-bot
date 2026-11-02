"""B-1448: every order this app sends to Kotak (place / cancel) logs one real_order_events row carrying the Kotak
order id and a reason, including a send Kotak accepts with an id and then marks 'rejected'. Before this, 155 Kotak
orders (mostly rejected SL retries) had no app row and the reconcile tagged them 'kotak_order_not_in_app_log'.

Run: pytest tests/test_b1448_rejections_logged.py -v
"""
import time
from contextlib import closing

import pytest

import kotak_neo
import kotak_real_fo_orders as kfo
import kotak_real_orders as k
import main


class _FakeKotak:
    """Accepts every order with a fresh nOrdNo, then reports it 'rejected' (or 'trigger pending')."""

    def __init__(self, reject=True, rej_reason="RMS:Rule: Check holding T1 holdings Used:2, Available:1",
                 cancel_error=None):
        self.reject, self.rej_reason, self.cancel_error = reject, rej_reason, cancel_error
        self.rows, self.sent, self.n = [], [], 0

    def place_order(self, **kw):
        self.n += 1
        oid = f"26110200{self.n:04d}"
        self.sent.append((oid, kw))
        self.rows.append({"nOrdNo": oid, "trdSym": kw["trading_symbol"], "trnsTp": kw["transaction_type"],
                          "prcTp": kw["order_type"], "qty": kw["quantity"], "trgPrc": kw.get("trigger_price", "0"),
                          "ordSt": "rejected" if self.reject else "trigger pending",
                          "rejRsn": self.rej_reason if self.reject else ""})
        return {"nOrdNo": oid, "stat": "Ok"}

    def order_report(self, order_id=None):
        rows = [r for r in self.rows if order_id is None or r["nOrdNo"] == str(order_id)]
        return {"data": rows}

    def cancel_order(self, order_id):
        if self.cancel_error:
            return {"error": self.cancel_error}
        return {"stat": "Ok", "nOrdNo": order_id}


@pytest.fixture
def kotak(monkeypatch):
    def make(**kw):
        fake = _FakeKotak(**kw)
        monkeypatch.setattr(kotak_neo, "login", lambda *a, **k2: fake)
        return fake
    monkeypatch.setattr(k, "_reference_prices", lambda s: (None, None))
    monkeypatch.setattr(k, "_tick_size_for", lambda s: 0.05)
    monkeypatch.setattr(k, "_STOP_FLOOR_PROVIDER", None)
    monkeypatch.setattr(k, "_before_equity_open", lambda: False)
    monkeypatch.setattr(k, "_in_closing_session", lambda: False)
    monkeypatch.setattr(k, "_RECENT_SL_PLACED", {})
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **kw: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(k.time, "sleep", lambda s: None)
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
    return make


def _rows(order_id=None):
    with closing(main.get_db()) as c:
        q = "SELECT leg, event, order_id, kotak_trading_symbol, detail FROM real_order_events"
        if order_id:
            return [dict(r) for r in c.execute(q + " WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()]
        return [dict(r) for r in c.execute(q + " ORDER BY id").fetchall()]


def _assert_rejection_logged(fake, leg, trdsym):
    assert fake.sent, "the path must still send the order to Kotak"
    for oid, _kw in fake.sent:
        rows = _rows(oid)
        assert len(rows) == 1, f"one row per Kotak order {oid}: {rows}"
        r = rows[0]
        assert (r["leg"], r["event"], r["kotak_trading_symbol"]) == (leg, "kotak_rejected", trdsym)
        assert r["detail"].startswith("reason: ") and "Kotak rejected it" in r["detail"]


def test_long_sl_retry_path_logs_rejected_order_id(kotak):
    fake = kotak()
    res = main._place_real_stop_loss_with_retry("TCS-EQ", 3, 3100.0)
    assert not res["ok"] and res["rejected_order_id"] == fake.sent[0][0]
    _assert_rejection_logged(fake, "sl", "TCS-EQ")
    assert "T1 holdings" in _rows(fake.sent[0][0])[0]["detail"]


def test_short_sl_heal_path_logs_rejected_order_id(kotak):
    fake = kotak(rej_reason="Order price is outside the valid price range")
    res = main._place_real_stop_loss_with_retry_short("INDIANB-EQ", 5, 610.0)
    assert not res["ok"]
    _assert_rejection_logged(fake, "short_sl", "INDIANB-EQ")


def test_swing_ensure_resting_sl_logs_rejected_order_id(kotak):
    fake = kotak()
    res = k.ensure_resting_sl("NYKAA-EQ", 10, 180.0)
    assert not res["ok"] and res["action"] == "placed"
    _assert_rejection_logged(fake, "sl", "NYKAA-EQ")
    assert _rows(fake.sent[0][0])[0]["detail"].count("reason:") == 1


def test_option_sl_rejection_logged(kotak):
    fake = kotak(rej_reason="Insufficient margin")
    res = kfo.place_real_fo_stop_loss("NIFTY26NOV24000CE", "nse_fo", 75, 100.0)
    assert not res["ok"]
    _assert_rejection_logged(fake, "fo_sl", "NIFTY26NOV24000CE")


def test_entry_rejection_logged(kotak):
    fake = kotak(rej_reason="Insufficient fund")
    assert not k.place_real_entry("SAIL-EQ", 1, 120.0)["ok"]
    _assert_rejection_logged(fake, "entry", "SAIL-EQ")


def test_send_error_without_order_id_logged(kotak, monkeypatch):
    fake = kotak()
    monkeypatch.setattr(fake, "place_order", lambda **kw: {"stat": "Not_Ok", "emsg": "bad"})
    monkeypatch.setattr(k, "_LOST_ACK_RECHECKS", ())
    assert not k.place_real_stop_loss("TCS-EQ", 1, 3000.0)["ok"]
    rows = _rows()
    assert [(r["leg"], r["event"]) for r in rows] == [("sl", "kotak_send_error")]
    assert "no order id in response" in rows[0]["detail"]


def test_cancel_failure_logged_with_order_id(kotak):
    kotak(cancel_error="order already complete")
    assert not k.cancel_real_order("999")["ok"]
    rows = _rows("999")
    assert [(r["leg"], r["event"]) for r in rows] == [("cancel", "kotak_cancel_failed")]
    assert "order already complete" in rows[0]["detail"]


def test_accepted_sl_covered_by_caller_row_is_not_duplicated(kotak):
    fake = kotak(reject=False)
    res = k.place_real_stop_loss("TCS-EQ", 1, 3000.0)
    oid = res["order_id"]
    assert _rows(oid) == []  # held briefly for the caller's own row
    with closing(main.get_db()) as c:
        main._log_real_order_event(c, "TCS.NS", "sl", "placed", kotak_trading_symbol="TCS-EQ", order_id=oid,
                                   reason="test caller row")
    assert [r["event"] for r in _rows(oid)] == ["placed"]
    assert fake.sent and main._PENDING_KOTAK_SENDS == []


def test_accepted_sl_no_caller_row_is_flushed_with_order_id(kotak, monkeypatch):
    kotak(reject=False)
    oid = k.place_real_stop_loss("TCS-EQ", 1, 3000.0)["order_id"]
    for ev in main._PENDING_KOTAK_SENDS:
        ev["ts"] -= 60
    with closing(main.get_db()) as c:
        assert main._flush_pending_kotak_sends(c) == 1
    rows = _rows(oid)
    assert [(r["leg"], r["event"]) for r in rows] == [("sl", "kotak_placed")]
    assert "Kotak accepted it" in rows[0]["detail"] and "trigger_price=3000.0" in rows[0]["detail"]


def test_repeated_rejection_still_logged_compactly(kotak):
    fake = kotak()
    for _ in range(3):
        k.place_real_stop_loss("TCS-EQ", 1, 3000.0)
    assert len(fake.sent) == 3
    details = [_rows(oid)[0]["detail"] for oid, _ in fake.sent]
    assert "Kotak rejRsn:" in details[0]
    assert "repeat #2" in details[1] and "repeat #3" in details[2]
    assert all(len(d) < len(details[0]) + 40 for d in details[1:])


def test_rejection_queued_when_db_locked_is_written_by_next_log_call(kotak, monkeypatch):
    fake = kotak()
    real_connect = main.sqlite3.connect

    def locked(*a, **kw):
        raise main.sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(main.sqlite3, "connect", locked)
    k.place_real_stop_loss("TCS-EQ", 1, 3000.0)
    monkeypatch.setattr(main.sqlite3, "connect", real_connect)
    oid = fake.sent[0][0]
    assert _rows(oid) == []
    with closing(main.get_db()) as c:
        main._log_real_order_event(c, "TCS.NS", "sl", "failed", kotak_trading_symbol="TCS-EQ", reason="caller")
    assert [r["event"] for r in _rows(oid)] == ["kotak_rejected"]


def test_reconcile_no_longer_tags_a_logged_rejection_as_unlogged(kotak):
    fake = kotak()
    k.place_real_stop_loss("TCS-EQ", 1, 3000.0)
    with closing(main.get_db()) as c:
        n = main._log_unlogged_kotak_orders(c, fake.order_report()["data"])
    assert n == 0
    assert not [r for r in _rows() if r["event"] == "kotak_order_not_in_app_log"]


def test_sends_unchanged_by_logging(kotak, monkeypatch):
    """The sink never alters what is sent or returned, even when it raises."""
    fake = kotak()
    monkeypatch.setattr(k, "_SEND_SINK", lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))
    res = k.place_real_stop_loss("TCS-EQ", 2, 3000.0)
    assert not res["ok"] and len(fake.sent) == 1 and fake.sent[0][1]["quantity"] == "2"
