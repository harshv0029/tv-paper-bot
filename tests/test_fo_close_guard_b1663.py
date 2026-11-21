"""B-1663: F&O/MCX/currency mirror of B-1581. A new SELL SL is never sent on a leg Kotak shows already sold or
exiting today; a partial exit protects only the remainder; a Kotak read failure fails open (protect). The F&O
market exit carries the in-flight close note. Also pins the B-1581 decorator placement: the short_cover send
recorder sits on place_real_short_cover, not on the shared close helper (else every long exit was recorded twice)."""
import kotak_real_fo_orders as kfo
import kotak_real_orders as kro

SYM = "NIFTY25NOV24000CE"


class _C:
    def __init__(self, rows, pos, fail_pos=False):
        self.rows, self.pos, self.fail_pos, self.sent = rows, pos, fail_pos, []

    def order_report(self, **k):
        return {"data": self.rows}

    def positions(self):
        if self.fail_pos:
            raise RuntimeError("down")
        return {"data": self.pos}

    def place_order(self, **k):
        self.sent.append(k)
        return {"nOrdNo": "N1"}


def _setup(monkeypatch, rows, pos, fail_pos=False):
    kro._EXIT_IN_FLIGHT.clear()
    c = _C(rows, pos, fail_pos)
    monkeypatch.setattr(kfo.kotak_neo, "login", lambda: c)
    monkeypatch.setattr(kro, "_confirm_order_status",
                        lambda oid: {"status": "trigger pending", "avg_price": None, "filled_qty": None})
    return c


def _pos(buy, sell):
    return [{"trdSym": SYM, "flBuyQty": str(buy), "flSellQty": str(sell)}]


def _sell(st, qty, fld, prc="MKT", oid="S1"):
    return {"trdSym": SYM, "trnsTp": "S", "prcTp": prc, "ordSt": st, "qty": str(qty), "fldQty": str(fld), "nOrdNo": oid}


def test_nothing_closed_today_places(monkeypatch):
    c = _setup(monkeypatch, [], _pos(50, 0))
    res = kfo.place_real_fo_stop_loss(SYM, "nse_fo", 50, 100.0)
    assert res["ok"] and len(c.sent) == 1 and c.sent[0]["quantity"] == "50"


def test_fully_sold_today_skips(monkeypatch):
    c = _setup(monkeypatch, [_sell("complete", 50, 50)], _pos(50, 50))
    res = kfo.place_real_fo_stop_loss(SYM, "nse_fo", 50, 100.0)
    assert res["action"] == "skipped_position_closed" and not c.sent


def test_working_market_exit_skips(monkeypatch):
    c = _setup(monkeypatch, [_sell("open", 50, 0)], _pos(50, 0))
    res = kfo.place_real_fo_stop_loss(SYM, "mcx_fo", 50, 100.0)
    assert res["action"] == "skipped_position_closed" and not c.sent


def test_in_flight_exit_not_yet_in_book_skips(monkeypatch):
    c = _setup(monkeypatch, [], _pos(50, 0))
    kro.note_exit_in_flight(SYM, "S", 50)
    res = kfo.place_real_fo_stop_loss(SYM, "nse_fo", 50, 100.0)
    assert res["action"] == "skipped_position_closed" and not c.sent


def test_partial_exit_protects_remainder(monkeypatch):
    c = _setup(monkeypatch, [_sell("complete", 25, 25)], _pos(75, 25))
    res = kfo.place_real_fo_stop_loss(SYM, "nse_fo", 75, 100.0)
    assert res["ok"] and c.sent[0]["quantity"] == "50"


def test_positions_unreadable_fails_open(monkeypatch):
    c = _setup(monkeypatch, [_sell("complete", 50, 50)], None, fail_pos=True)
    res = kfo.place_real_fo_stop_loss(SYM, "nse_fo", 50, 100.0)
    assert res["ok"] and len(c.sent) == 1


def test_trailing_replace_does_not_restore_on_closed_leg(monkeypatch):
    c = _setup(monkeypatch, [_sell("complete", 50, 50)], _pos(50, 50))
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: {"ok": True})
    res = kfo.ensure_option_trailing_sl(SYM, "nse_fo", 50, 120.0, [{"order_id": "O1", "trigger": 100.0, "qty": 50}])
    assert res["action"] == "skipped_position_closed" and not c.sent


def test_fo_exit_sets_in_flight_note(monkeypatch):
    c = _setup(monkeypatch, [], _pos(50, 0))
    res = kfo.place_real_fo_exit(SYM, "nse_fo", 50)
    assert res["ok"] and kro._exit_in_flight(SYM, "S")["order_id"] == "N1"
    assert c.sent[0]["transaction_type"] == "S" and c.sent[0]["order_type"] == "MKT"


def test_short_cover_recorder_on_the_right_function(monkeypatch):
    legs = []
    monkeypatch.setattr(kro, "_report_send", lambda leg, purpose, first, res, **k: legs.append(leg))
    monkeypatch.setattr(kro, "_confirm_order_status", lambda oid: {"status": "complete", "avg_price": 10.0, "filled_qty": 1})
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C([], []))
    monkeypatch.setattr(kro, "_fetch_ltp", lambda *a, **k: 10.0, raising=False)
    kro._EXIT_IN_FLIGHT.clear()
    kro.place_real_short_cover("X-EQ", 1)
    assert legs == ["short_cover"]
    legs.clear()
    kro.place_real_exit("X-EQ", 1)
    assert legs == ["exit"]
