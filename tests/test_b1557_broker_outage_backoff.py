"""B-1557: a broker-wide Kotak outage ("ADAPTER is down" on every order) backs SL resends off to 60 s per symbol,
raises one reasoned outage event, and the first accepted send restores normal cadence. First attempts always go out."""
import time

import pytest

import kotak_real_orders as kro


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    kro._OUTAGE_FAILS.clear()
    kro._OUTAGE_STATE.update(since=None, skipped=0, last_detail=None)
    events = []
    monkeypatch.setattr(kro, "_SEND_SINK", events.append)
    yield events
    kro._OUTAGE_FAILS.clear()
    kro._OUTAGE_STATE.update(since=None, skipped=0, last_detail=None)


def _mk(leg, outcome):
    calls = []

    @kro._records_send(leg, "test send")
    def send(trdsym, *a, **k):
        calls.append(trdsym)
        return dict(outcome[0])
    return send, calls


DOWN = {"ok": False, "detail": "place_order raised: ADAPTER is down"}


def test_single_symbol_failure_is_not_an_outage():
    send, calls = _mk("sl", [DOWN])
    send("AAA-EQ", 1, 10.0)
    send("AAA-EQ", 1, 10.0)
    assert calls == ["AAA-EQ", "AAA-EQ"]  # one symbol alone never throttles
    assert not kro.broker_outage_active()


def test_outage_backs_off_sl_resends_and_logs_once(_reset):
    outcome = [DOWN]
    send, calls = _mk("sl", outcome)
    send("AAA-EQ", 1, 10.0)
    send("BBB-EQ", 1, 10.0)
    assert kro.broker_outage_active()
    assert [e["event"] for e in _reset].count("broker_outage_detected") == 1
    r = send("AAA-EQ", 1, 10.0)  # within 60 s: not sent
    assert r["action"] == "skipped_broker_outage_backoff" and r["ok"] is False
    assert calls == ["AAA-EQ", "BBB-EQ"]
    send("CCC-EQ", 1, 10.0)  # a symbol's first attempt always goes out
    assert calls[-1] == "CCC-EQ"
    kro._OUTAGE_FAILS["AAA-EQ"] = time.time() - kro.BROKER_OUTAGE_SL_BACKOFF_S - 1
    send("AAA-EQ", 1, 10.0)  # after 60 s it is retried
    assert calls[-1] == "AAA-EQ"
    assert kro.broker_outage_status()["active"] is True


def test_non_sl_legs_are_never_skipped_and_success_clears():
    send_sl, sl_calls = _mk("sl", [DOWN])
    send_sl("AAA-EQ", 1, 10.0)
    send_sl("BBB-EQ", 1, 10.0)
    exit_send, exit_calls = _mk("exit", [{"ok": True, "order_id": "1"}])
    exit_send("AAA-EQ", 1)  # exits/entries always go out
    assert exit_calls == ["AAA-EQ"]
    assert not kro.broker_outage_active()  # first accepted send clears the outage
    send_sl("AAA-EQ", 1, 10.0)
    assert sl_calls[-1] == "AAA-EQ"


def test_login_throttle_counts_as_outage_marker():
    assert kro._is_outage_detail({"ok": False, "detail": "login failed: too many request received"})
    assert not kro._is_outage_detail({"ok": False, "detail": "Kotak rejected: price outside range"})
