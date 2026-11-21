"""B-1581 (UPL 18-Nov 09:15, CANBK 19-Nov 11:16 IST live): an exit sweep cancelled the stop and sent a market close
while another protect pass, on an order book read before that exit existed, sent a fresh stop seconds later (Kotak:
"Check T1 holdings"). This process now marks its own close in flight, so the closed-position guard counts it before
Kotak's book shows it; a partial close keeps the remainder protected; a failed close resumes protection at once."""
import kotak_real_orders as kro


def _reset():
    kro._EXIT_IN_FLIGHT.clear()


def test_in_flight_close_counts_before_book_shows_it(monkeypatch):
    _reset()
    monkeypatch.setattr(kro, "_holdings_gross_qty", lambda t: 2)
    assert kro._position_already_closed("CANBK-EQ", 2, "S", rows=[]) is None  # nothing closing: protect
    kro.note_exit_in_flight("CANBK-EQ", "S", 2)
    skip = kro._position_already_closed("CANBK-EQ", 2, "S", rows=[])
    assert skip and skip["action"] == "skipped_position_closed"


def test_partial_close_keeps_remainder_protected(monkeypatch):
    _reset()
    monkeypatch.setattr(kro, "_holdings_gross_qty", lambda t: 4)
    kro.note_exit_in_flight("X-EQ", "S", 2)
    assert kro._position_already_closed("X-EQ", 2, "S", rows=[]) is None


def test_close_already_in_book_not_double_counted(monkeypatch):
    _reset()
    monkeypatch.setattr(kro, "_holdings_gross_qty", lambda t: 4)
    kro.note_exit_in_flight("X-EQ", "S", 2, order_id="E1")
    rows = [{"trdSym": "X-EQ", "trnsTp": "S", "ordSt": "complete", "qty": "2", "fldQty": "2", "nOrdNo": "E1"}]
    assert kro._position_already_closed("X-EQ", 2, "S", rows=rows) is None  # 4 - 2 = 2 still held


def test_note_expires(monkeypatch):
    _reset()
    kro.note_exit_in_flight("X-EQ", "S", 2)
    kro._EXIT_IN_FLIGHT[("X-EQ", "S")]["ts"] -= kro.EXIT_IN_FLIGHT_WINDOW_S + 1
    assert kro._exit_in_flight("X-EQ", "S") is None


class _C:
    def __init__(self, fail=False):
        self.fail = fail

    def place_order(self, **k):
        if self.fail:
            raise RuntimeError("adapter down")
        return {"nOrdNo": "E9"}


def _filled(monkeypatch):
    monkeypatch.setattr(kro, "_confirm_order_status", lambda oid: {"status": "complete", "avg_price": 10.0, "filled_qty": 3})


def test_exit_keeps_note_on_success_and_clears_on_failure(monkeypatch):
    _reset()
    _filled(monkeypatch)
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C())
    assert kro.place_real_exit("A-EQ", 3)["ok"]
    assert kro._exit_in_flight("A-EQ", "S")["order_id"] == "E9"
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C(fail=True))
    assert not kro.place_real_exit("A-EQ", 3)["ok"]
    assert kro._exit_in_flight("A-EQ", "S") is None


def test_short_cover_marks_buy_side(monkeypatch):
    _reset()
    _filled(monkeypatch)
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C())
    assert kro.place_real_short_cover("S-EQ", 5)["ok"]
    assert kro._exit_in_flight("S-EQ", "B")["qty"] == 5 and kro._exit_in_flight("S-EQ", "S") is None


def test_failed_cancel_clears_note(monkeypatch):
    _reset()
    monkeypatch.setattr(kro, "_cancel_all_open_sells", lambda t: {"ok": False})
    kro.cancel_all_open_sells("B-EQ", exit_qty=2)
    assert kro._exit_in_flight("B-EQ", "S") is None
    monkeypatch.setattr(kro, "_cancel_all_open_sells", lambda t: {"ok": True, "cancelled": []})
    kro.cancel_all_open_sells("B-EQ", exit_qty=2)
    assert kro._exit_in_flight("B-EQ", "S")["qty"] == 2


def test_stop_skipped_even_after_ensure_checked_an_older_book(monkeypatch):
    _reset()
    sent = []
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro, "_holdings_gross_qty", lambda t: 2)
    monkeypatch.setattr(kro, "_position_already_closed",
                        lambda t, q, s, rows=None: kro.__dict__["_orig_pac"](t, q, s, rows=[]))
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked", lambda *a, **k: sent.append(a) or {"ok": True, "order_id": "SL"})
    kro.note_exit_in_flight("U-EQ", "S", 2)
    kro._CLOSED_CHECKED.on = True  # ensure_resting_sl ran its check on a book read before the close
    try:
        res = kro.place_real_stop_loss("U-EQ", 2, 100.0)
    finally:
        kro._CLOSED_CHECKED.on = False
    assert res["action"] == "skipped_position_closed" and not sent


def test_short_stop_skipped_while_cover_in_flight(monkeypatch):
    _reset()
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: type("C", (), {"order_report": lambda self: {"data": []}})())
    kro.note_exit_in_flight("S-EQ", "B", 5)
    res = kro.place_real_short_stop_loss("S-EQ", 5, 100.0)
    assert res["action"] == "skipped_position_closed"


kro.__dict__.setdefault("_orig_pac", kro._position_already_closed)
