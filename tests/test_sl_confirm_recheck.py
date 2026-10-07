import kotak_real_orders as k


class _C:
    def place_order(self, **kw):
        return {"nOrdNo": "1"}


def _run(monkeypatch, seq):
    monkeypatch.setattr(k.kotak_neo, "login", lambda: _C())
    monkeypatch.setattr(k.time, "sleep", lambda s: None)
    it = iter(seq)
    monkeypatch.setattr(k, "_confirm_order_status", lambda oid: next(it))
    return k.place_real_stop_loss("RVNL-EQ", 2, 193.25)


def _st(s):
    return {"status": s, "detail": "RMS reject" if s == "rejected" else None, "row": None}


def test_unknown_then_rejected_is_failure(monkeypatch):
    assert _run(monkeypatch, [_st("unknown"), _st("rejected")])["ok"] is False


def test_unknown_then_trigger_pending_is_ok(monkeypatch):
    r = _run(monkeypatch, [_st("unknown"), _st("trigger pending")])
    assert r["ok"] and r["status_confirmed"]
