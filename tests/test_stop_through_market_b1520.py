"""B-1520 (IOC 2026-11-09: no resting SL from the 09:15 IST open until 09:26:19 IST). A trailed stop the market had
already gone through was re-sent (and refused) while nothing rested. Every real stop is now checked against a fresh
live price: a stop through the market rests just under it (long) / over it (short) and the swing callers exit at
market, as the replay fills at the open."""
import time
from contextlib import closing

import pytest

import kotak_live_feed
import kotak_real_orders as kro
import main


@pytest.fixture
def _mkt(monkeypatch):
    state = {"ltp": None}
    monkeypatch.setattr(kro, "_LTP_PROVIDER", lambda trd: state["ltp"])
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", lambda trd, side: None)
    monkeypatch.setattr(kro, "_band_reference", lambda trd: (None, None))
    monkeypatch.setattr(kro, "_tick_size_for", lambda trd: 0.01)
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    return state


def test_long_stop_through_market_rests_under_the_ltp(_mkt):
    _mkt["ltp"] = 141.20
    trg, info = kro.clamp_stop_to_market("IOC-EQ", 141.66, "long")
    assert trg == 140.49 and trg < 141.20 and info == {"stop_through_market": 141.66, "ltp": 141.20}


def test_placeable_or_unknown_price_is_unchanged(_mkt):
    _mkt["ltp"] = 143.0
    assert kro.clamp_stop_to_market("IOC-EQ", 141.66, "long") == (141.66, {})
    _mkt["ltp"] = None
    assert kro.clamp_stop_to_market("IOC-EQ", 141.66, "long") == (141.66, {})


def test_short_mirror(_mkt):
    _mkt["ltp"] = 101.0
    trg, info = kro.clamp_stop_to_market("S-EQ", 100.5, "short")
    assert trg == 101.51 and info["stop_through_market"] == 100.5
    assert kro.clamp_stop_to_market("S-EQ", 103.0, "short") == (103.0, {})


def test_place_long_and_short_send_the_placeable_level(_mkt, monkeypatch):
    _mkt["ltp"] = 141.20
    sent = []
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    res = kro.place_real_stop_loss("IOC-EQ", 1, 141.66)
    assert sent == [140.49] and res["stop_through_market"] == 141.66
    _mkt["ltp"] = 101.0
    monkeypatch.setattr(kro, "_place_real_short_stop_loss_once",
                        lambda trd, q, t, p="MIS": sent.append(t) or {"ok": True, "order_id": "2", "trigger_price": t})
    res = kro.place_real_short_stop_loss("S-EQ", 1, 100.5)
    assert sent[-1] == 101.51 and res["stop_through_market"] == 100.5


def _book(monkeypatch, rows):
    class _C:
        def order_report(self):
            return {"data": rows}
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C())
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)


def test_ensure_places_placeable_level_and_flags(_mkt, monkeypatch):
    _mkt["ltp"] = 141.20
    _book(monkeypatch, [])
    sent = []
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "N", "trigger_price": t})
    kro._RECENT_SL_PLACED.pop("IOC-EQ", None)
    res = kro.ensure_resting_sl("IOC-EQ", 1, 141.66)
    kro._RECENT_SL_PLACED.pop("IOC-EQ", None)
    assert res["ok"] and res["action"] == "placed" and sent == [140.49] and res["stop_through_market"] == 141.66


def test_ensure_adopts_a_live_sl_at_the_placeable_level_no_churn(_mkt, monkeypatch):
    _mkt["ltp"] = 141.20
    _book(monkeypatch, [{"trdSym": "IOC-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending",
                         "nOrdNo": "OLD", "trgPrc": "140.49", "qty": "1"}])
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: pytest.fail("must not cancel"))
    kro._RECENT_SL_PLACED.pop("IOC-EQ", None)
    res = kro.ensure_resting_sl("IOC-EQ", 1, 141.66)
    assert res["action"] == "adopted_existing" and res["stop_through_market"] == 141.66


def test_fresh_ltp_provider_ignores_stale_and_previous_session_ticks(monkeypatch):
    now = time.time()
    ticks = {"IOC.NS": {"ltp": 141.2, "trading_symbol": "IOC-EQ", "updated_at_utc": now - 5,
                        "last_trade_epoch": now - 5}}
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: dict(ticks))
    assert main._fresh_ltp_for_trdsym("IOC-EQ", now=now) == 141.2
    ticks["IOC.NS"] = dict(ticks["IOC.NS"], updated_at_utc=now - 600)
    assert main._fresh_ltp_for_trdsym("IOC-EQ", now=now) is None
    ticks["IOC.NS"] = dict(ticks["IOC.NS"], updated_at_utc=now - 5, last_trade_epoch=now - 3 * 86400)
    assert main._fresh_ltp_for_trdsym("IOC-EQ", now=now) is None
    assert main._fresh_ltp_for_trdsym("NONE-EQ", now=now) is None


def test_swing_caller_exits_at_market_when_flagged(monkeypatch):
    main.init_db()
    calls = []
    monkeypatch.setattr(main, "_swing_stop_breached_exit",
                        lambda conn, sym, stop, ltp, label="": calls.append((sym, stop, ltp)) or True)
    with closing(main.get_db()) as c:
        assert main._swing_exit_if_stop_through_market(c, "IOC.NS", {"ok": True, "trigger_price": 140.49}) is False
        assert main._swing_exit_if_stop_through_market(
            c, "IOC.NS", {"ok": True, "trigger_price": 140.49, "stop_through_market": 141.66, "ltp": 141.2}) is True
        ev = c.execute("SELECT event, detail FROM real_order_events WHERE symbol='IOC.NS' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert calls == [("IOC.NS", 141.66, 141.2)]
    assert ev[0] == "stop_through_market" and "B-1520" in ev[1]
