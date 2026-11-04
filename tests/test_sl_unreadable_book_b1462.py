"""B-1462: a periodic SL re-check never places a stop-loss blind when Kotak's order book cannot be read."""
import kotak_real_orders as kro


class _Client:
    def __init__(self, reports):
        self.reports = list(reports)
        self.calls = 0

    def order_report(self):
        self.calls += 1
        r = self.reports.pop(0) if self.reports else {"stat": "Not_Ok"}
        if isinstance(r, Exception):
            raise r
        return r


def _setup(monkeypatch, reports):
    c = _Client(reports)
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: c)
    monkeypatch.setattr(kro, "ORDER_BOOK_READ_RETRY_DELAYS_S", (0.0, 0.0))
    placed = []
    monkeypatch.setattr(kro, "place_real_stop_loss",
                        lambda t, q, p: placed.append((t, q, p)) or {"ok": True, "order_id": "X", "trigger_price": p})
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    monkeypatch.setattr(kro, "apply_entry_day_floor", lambda t, p, side: (p, None))
    monkeypatch.setattr(kro, "_tick_size_for", lambda t: 0.01)
    kro._RECENT_SL_PLACED.pop("BANKINDIA-EQ", None)
    return c, placed


LIVE = {"data": [{"trdSym": "BANKINDIA-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending", "qty": 8,
                  "trgPrc": "126.73", "nOrdNo": "1"}]}


def test_periodic_check_skips_when_book_unreadable(monkeypatch):
    c, placed = _setup(monkeypatch, [{"stat": "Not_Ok"}, RuntimeError("timeout"), {"stat": "Not_Ok"}])
    r = kro.ensure_resting_sl("BANKINDIA-EQ", 8, 126.73, allow_unchecked=False)
    assert r["action"] == "skipped_unreadable_book" and not r["ok"]
    assert placed == [] and c.calls == 3


def test_retry_finds_live_sl_and_adopts(monkeypatch):
    c, placed = _setup(monkeypatch, [RuntimeError("timeout"), LIVE])
    r = kro.ensure_resting_sl("BANKINDIA-EQ", 8, 126.73, allow_unchecked=False)
    assert r["action"] == "adopted_existing" and placed == []


def test_entry_path_still_places_when_unreadable(monkeypatch):
    c, placed = _setup(monkeypatch, [{"stat": "Not_Ok"}] * 3)
    r = kro.ensure_resting_sl("BANKINDIA-EQ", 8, 126.73)
    assert r["action"] == "placed_unchecked" and placed == [("BANKINDIA-EQ", 8, 126.73)]
