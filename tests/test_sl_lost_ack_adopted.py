"""B-1338: a timed-out SL request that Kotak placed anyway is adopted, never reported as failed."""
import kotak_real_orders as kro


class _Client:
    def __init__(self, rows, raise_on_place=True):
        self.rows, self.raise_on_place, self.placed = rows, raise_on_place, 0

    def place_order(self, **kw):
        self.placed += 1
        raise TimeoutError("Request timeout after 30 seconds")

    def order_report(self):
        return {"data": self.rows}


def _run(monkeypatch, rows):
    client = _Client(rows)
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: client)
    monkeypatch.setattr(kro.time, "sleep", lambda s: None)
    monkeypatch.setattr(kro, "_tick_size_for", lambda s: 0.01)
    return client, kro._place_real_stop_loss_once("WIPRO-EQ", 1, 186.86)


def test_timeout_then_live_sl_is_adopted(monkeypatch):
    rows = [{"trdSym": "WIPRO-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending",
             "nOrdNo": "261022000123", "trgPrc": "186.86"}]
    client, res = _run(monkeypatch, rows)
    assert res["ok"] and res["order_id"] == "261022000123" and res["adopted_after_lost_ack"]
    assert client.placed == 1


def test_timeout_and_no_order_stays_failed(monkeypatch):
    rows = [{"trdSym": "WIPRO-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "rejected",
             "nOrdNo": "1", "trgPrc": "186.86"},
            {"trdSym": "INFY-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending",
             "nOrdNo": "2", "trgPrc": "186.86"}]
    _, res = _run(monkeypatch, rows)
    assert not res["ok"] and "timeout" in res["detail"]
