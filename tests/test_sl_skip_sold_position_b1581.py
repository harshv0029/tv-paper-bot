"""B-1581 (NMDC 13-Nov-2026): a swing rule-exit SELL filled 09:18:57 IST, then the 5-min backfill sent a new SELL SL at
09:19:05 (Kotak: "Check T1 holdings ... Used:12, Available:6"). No new stop may be placed on a position Kotak's own
order book + holdings show as already sold / exiting today, for longs and shorts. Fails open when Kotak is unreadable."""
import kotak_real_orders as kro


def _o(oid, side, st, qty, prc="MKT", fld=None, sym="NMDC-EQ", t="13-Nov-2026 09:18:57"):
    return {"nOrdNo": oid, "trdSym": sym, "trnsTp": side, "ordSt": st, "qty": str(qty), "prcTp": prc,
            "fldQty": str(qty if fld is None and st == "complete" else (fld or 0)), "ordDtTm": t}


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def order_report(self):
        return {"data": self.rows}


def _setup(monkeypatch, rows, holding_qty=6):
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _Client(rows))
    monkeypatch.setattr(kro.kotak_neo, "holdings", lambda: {"data": [
        {"exchangeSegment": "nse_cm", "symbol": "NMDC", "series": "EQ", "quantity": holding_qty}]})
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    sent = []
    monkeypatch.setattr(kro, "_place_real_stop_loss_unlocked",
                        lambda s, q, t: sent.append((s, q, t)) or {"ok": True, "order_id": "NEW", "trigger_price": t})
    monkeypatch.setattr(kro, "apply_entry_day_floor", lambda s, t, side: (t, {}))
    monkeypatch.setattr(kro, "clamp_stop_to_market", lambda s, t, side: (t, {}))
    monkeypatch.setattr(kro, "_tick_size_for", lambda s: 0.01)
    kro._RECENT_SL_PLACED.pop("NMDC-EQ", None)
    return sent


NMDC_BOOK = [_o("261113000013997", "S", "cancelled", 6, prc="SL"), _o("261113000032545", "S", "complete", 6)]


def test_nmdc_swing_backfill_skips_sold_holding(monkeypatch):
    sent = _setup(monkeypatch, NMDC_BOOK)
    r = kro.ensure_resting_sl("NMDC-EQ", 6, 67.27)
    assert r["action"] == "skipped_position_closed" and not r["ok"] and sent == []


def test_direct_place_real_stop_loss_also_skips(monkeypatch):
    sent = _setup(monkeypatch, NMDC_BOOK)
    r = kro.place_real_stop_loss("NMDC-EQ", 6, 67.27)
    assert r["action"] == "skipped_position_closed" and sent == []


def test_market_exit_still_working_counts_as_closed(monkeypatch):
    sent = _setup(monkeypatch, [_o("X", "S", "open", 6)])
    assert kro.ensure_resting_sl("NMDC-EQ", 6, 67.27)["action"] == "skipped_position_closed" and sent == []


def test_partial_manual_sell_keeps_rest_protected(monkeypatch):
    sent = _setup(monkeypatch, [_o("X", "S", "complete", 3)])  # 6 held, 3 sold, row corrected to 3
    r = kro.ensure_resting_sl("NMDC-EQ", 3, 67.27)
    assert r["ok"] and sent == [("NMDC-EQ", 3, 67.27)]


def test_intraday_staged_leg_rest_still_protected(monkeypatch):
    sent = _setup(monkeypatch, [_o("B1", "B", "complete", 3, prc="L"), _o("S1", "S", "complete", 2, prc="L")],
                  holding_qty=0)
    r = kro.place_real_stop_loss("NMDC-EQ", 1, 67.27)
    assert r["ok"] and sent == [("NMDC-EQ", 1, 67.27)]


def test_intraday_fully_exited_skips(monkeypatch):
    sent = _setup(monkeypatch, [_o("B1", "B", "complete", 3, prc="L"), _o("S1", "S", "complete", 3)], holding_qty=0)
    assert kro.place_real_stop_loss("NMDC-EQ", 3, 67.27)["action"] == "skipped_position_closed" and sent == []


def test_no_sell_today_places_normally(monkeypatch):
    sent = _setup(monkeypatch, [])
    assert kro.ensure_resting_sl("NMDC-EQ", 6, 67.27)["action"] == "placed" and len(sent) == 1


def test_holdings_unreadable_fails_open(monkeypatch):
    sent = _setup(monkeypatch, NMDC_BOOK)

    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(kro.kotak_neo, "holdings", boom)
    assert kro.ensure_resting_sl("NMDC-EQ", 6, 67.27)["action"] == "placed" and len(sent) == 1


def test_short_cover_skips_new_buy_stop(monkeypatch):
    _setup(monkeypatch, [_o("E", "S", "complete", 5, prc="L"), _o("C", "B", "complete", 5)])
    called = []
    monkeypatch.setattr(kro, "_place_real_short_stop_loss_once", lambda *a, **k: called.append(a) or {"ok": True})
    r = kro.place_real_short_stop_loss("NMDC-EQ", 5, 80.0)
    assert r["action"] == "skipped_position_closed" and called == []


def test_short_still_open_places(monkeypatch):
    _setup(monkeypatch, [_o("E", "S", "complete", 5, prc="L")])
    monkeypatch.setattr(kro, "_preclamp_short_stop", lambda s, t: (t, None))
    called = []
    monkeypatch.setattr(kro, "_place_real_short_stop_loss_once",
                        lambda *a, **k: called.append(a) or {"ok": True, "order_id": "N", "trigger_price": 80.0})
    assert kro.place_real_short_stop_loss("NMDC-EQ", 5, 80.0)["ok"] and len(called) == 1
