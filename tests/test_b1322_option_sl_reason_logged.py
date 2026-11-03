"""B-1322 (JIOFIN26OCT217.5CE, 21 Oct 2026: bought 2350 @2.54 09:52:36 IST, no SELL SL of any status ever reached
Kotak, unwound 12 s later, no reason anywhere). Every way an option SL attempt can fail WITHOUT a Kotak order id
now writes a reasoned real_order_events row, the unwind carries "entry SL could not be placed: <cause>", and a
SELL SL whose trigger is at/above the LTP is refused before any send. Kotak is fully mocked."""
import os
import tempfile
import time
from contextlib import closing

import pytest

import kotak_neo
import kotak_real_fo_orders as kfo
import kotak_real_orders as kro
import main
import nse_fo_chain

CONTRACT = {"kotak_trading_symbol": "JIOFIN26OCT217.5CE", "instrument_token": "77", "exchange_segment": "nse_fo",
            "expiry": "2099-10-28", "strike": 217.5, "lot_size": 2350, "premium": 2.54}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **kw: None)
    monkeypatch.setattr(kro, "_LAST_REJECTION", {})
    main._fo_last_sl_cause.clear(); main._fo_sl_unreadable_logged.clear(); main._fo_sl_unprotected_since.clear()
    yield


def _events():
    with closing(main.get_db()) as c:
        return [dict(r) for r in c.execute("SELECT leg, event, order_id, detail FROM real_order_events ORDER BY id")]


def _insert_leg(conn, entry=2.54, opened=None, trig=None, sl_oid=None):
    conn.execute(
        "INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, "
        "exchange_segment, expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, "
        "sl_order_id, sl_trigger_price, peak_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("JIOFIN:CALL", "JIOFIN", "single_leg_call", CONTRACT["kotak_trading_symbol"], "77", "nse_fo", "2099-10-28",
         217.5, 2350, 2350, entry, "E1", opened or time.time() - 600, "2026-10-21", sl_oid, trig, entry))
    conn.commit()


def _sync_env(monkeypatch, ltp, state):
    monkeypatch.setattr(kfo, "fetch_kotak_option_state", lambda s: state)
    monkeypatch.setattr(main, "_option_ltp", lambda r: ltp)
    monkeypatch.setattr(main, "kotak_real_orders_closing_session", lambda: False)
    monkeypatch.setattr(nse_fo_chain, "must_force_close_before_expiry", lambda u, e: False)


# --- step 3: the 21 Oct numbers are placeable; trigger >= LTP is refused before the send ---------------------

def test_jiofin_2_54_initial_stop_is_a_valid_tick_below_ltp():
    ok, why, trig, lim = kfo.option_sl_precheck(2.54 * (1 - main.FO_OPTION_INITIAL_STOP_PCT / 100.0), ltp=2.51)
    assert ok, why
    assert (trig, lim) == (2.45, 2.3)


@pytest.mark.parametrize("trigger,ltp,frag", [(2.45, 2.45, "at/above LTP"), (2.50, 2.45, "at/above LTP"),
                                              (0.05, None, "not a positive tick"), (0, None, "not positive")])
def test_precheck_refusals(trigger, ltp, frag):
    ok, why, _, _ = kfo.option_sl_precheck(trigger, ltp=ltp)
    assert not ok and frag in why


def test_place_sl_precheck_refusal_never_logs_in_and_is_logged(monkeypatch):
    monkeypatch.setattr(kotak_neo, "login", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")))
    res = kfo.place_real_fo_stop_loss(CONTRACT["kotak_trading_symbol"], "nse_fo", 2350, 0.05)
    assert not res["ok"] and res["detail"].startswith("precheck failed")
    ev = [e for e in _events() if e["event"] == "sl_precheck_failed"]
    assert len(ev) == 1 and ev[0]["leg"] == "fo_sl" and "NOT sent to Kotak" in ev[0]["detail"]


def test_login_failure_on_sl_send_is_logged_once_per_window(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("token expired")
    monkeypatch.setattr(kotak_neo, "login", _boom)
    for _ in range(3):
        assert not kfo.place_real_fo_stop_loss(CONTRACT["kotak_trading_symbol"], "nse_fo", 2350, 2.45)["ok"]
    ev = [e for e in _events() if e["event"] == "kotak_login_failed"]
    assert len(ev) == 1 and "token expired" in ev[0]["detail"] and "reason:" in ev[0]["detail"]


def test_sync_trigger_above_ltp_with_no_live_sl_exits_at_market(monkeypatch):
    # B-1459: premium 2.40 is already under the 2.45 initial stop: no SL is sent, the leg is exited at market.
    sent, closed = [], []
    _sync_env(monkeypatch, ltp=2.40, state={"ok": True, "net_qty": 2350, "live_sls": []})
    monkeypatch.setattr(kfo, "ensure_option_trailing_sl", lambda *a, **k: sent.append(a) or {"ok": True})
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda c, r, why: closed.append(why) or True)
    with closing(main.get_db()) as c:
        _insert_leg(c)
        assert main._sync_real_fo_option_sl(c, "JIOFIN:CALL", reason="initial protective SL right after entry") \
            == "trail_breached_exit"
    assert not sent
    assert closed and "B-1459 trail breached" in closed[0] and "2.4" in closed[0]


def test_sync_trail_above_ltp_with_live_lower_sl_exits_at_market(monkeypatch):
    # B-1459: trail 2.75 (peak 2.80) is above LTP 2.60; holding on the old 2.45 stop is refused: exit at market.
    sent, closed = [], []
    live = [{"order_id": "SL9", "trigger": 2.45, "qty": 2350}]
    _sync_env(monkeypatch, ltp=2.60, state={"ok": True, "net_qty": 2350, "live_sls": live})
    monkeypatch.setattr(main, "_option_feed_high_since", lambda c, r: 2.80)  # trail 2.77 > LTP 2.60
    monkeypatch.setattr(kfo, "ensure_option_trailing_sl", lambda *a, **k: sent.append(a) or {"ok": True})
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda c, r, why: closed.append(why) or True)
    with closing(main.get_db()) as c:
        _insert_leg(c, trig=2.45, sl_oid="SL9")
        assert main._sync_real_fo_option_sl(c, "JIOFIN:CALL") == "trail_breached_exit"
    assert not sent
    assert closed and "SL 2.75" in closed[0] and "resting trigger 2.45" in closed[0]


def test_sync_non_ltp_precheck_refusal_keeps_live_sl(monkeypatch):
    # A refusal NOT caused by LTP (bad tick) still keeps the live SL as before.
    live = [{"order_id": "SL9", "trigger": 2.45, "qty": 2350}]
    _sync_env(monkeypatch, ltp=2.60, state={"ok": True, "net_qty": 2350, "live_sls": live})
    monkeypatch.setattr(kfo, "option_sl_precheck", lambda d, l: (False, "limit not a positive tick", 0.05, 0.0))
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda c, r, why: (_ for _ in ()).throw(AssertionError("no exit")))
    with closing(main.get_db()) as c:
        _insert_leg(c, trig=2.45, sl_oid="SL9")
        assert main._sync_real_fo_option_sl(c, "JIOFIN:CALL") == "kept_existing_precheck_refused"


def test_sync_kotak_unreadable_logs_reason_once(monkeypatch):
    _sync_env(monkeypatch, ltp=2.51, state={"ok": False, "detail": "positions unreadable: None"})
    with closing(main.get_db()) as c:
        _insert_leg(c, opened=time.time() - 5)
        for _ in range(3):
            assert main._sync_real_fo_option_sl(c, "JIOFIN:CALL").startswith("kotak_unreadable")
    ev = [e for e in _events() if e["event"] == "sl_precheck_failed"]
    assert len(ev) == 1 and "Kotak state unreadable" in ev[0]["detail"]


# --- step 2/4: an exception before the send is recorded and the unwind carries the cause ---------------------

def _patch_buy(monkeypatch, closed):
    monkeypatch.setattr(main, "_option_pool_allows", lambda t: True)
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1e9)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {"ok": True, "real_pnl_today": 0.0, "detail": "", "cap_inr": None})
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity", lambda c: {})
    monkeypatch.setattr(kfo, "check_margin_affordable", lambda **k: {"ok": True})
    monkeypatch.setattr(kfo, "place_real_fo_entry", lambda *a, **k: {"ok": True, "order_id": "E1"})
    monkeypatch.setattr(main, "FO_ENTRY_SL_FAIL_RETRY_WINDOW_S", 0.0)
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, why: closed.append(why))


def test_entry_sl_exception_is_logged_and_unwind_reason_names_it(monkeypatch):
    closed = []
    _patch_buy(monkeypatch, closed)

    def _raise(conn, leg, reason=""):
        raise KeyError("trgPrc")
    monkeypatch.setattr(main, "_sync_real_fo_option_sl", _raise)
    with closing(main.get_db()) as c:
        main._real_fo_buy_contract(c, "JIOFIN:CALL", "JIOFIN", dict(CONTRACT, premium=25.0), "x", "single_leg_call", "t")
    assert closed and closed[0].startswith("entry SL could not be placed: exception before/around the SL send: KeyError")
    assert "entry unwound" in closed[0]
    ev = [e for e in _events() if e["event"] == "sl_exception"]
    assert ev and ev[0]["leg"] == "fo_sl" and "KeyError" in ev[0]["detail"]


def test_entry_unwind_reason_uses_recorded_cause(monkeypatch):
    closed = []
    _patch_buy(monkeypatch, closed)

    def _fail(conn, leg, reason=""):
        main._fo_last_sl_cause[leg] = "no order id in response: {'stCode': 1009}"
        return "sl_failed"
    monkeypatch.setattr(main, "_sync_real_fo_option_sl", _fail)
    with closing(main.get_db()) as c:
        main._real_fo_buy_contract(c, "JIOFIN:CALL", "JIOFIN", dict(CONTRACT, premium=25.0), "x", "single_leg_call", "t")
    assert closed == ["entry SL could not be placed: no order id in response: {'stCode': 1009}; entry unwound (status sl_failed)"]


def test_fo_unwind_exit_row_reaches_reasoned_order_log(monkeypatch):
    monkeypatch.setattr(kfo, "fetch_kotak_option_state", lambda s: {"ok": True, "net_qty": 2350, "live_sls": []})
    monkeypatch.setattr(kfo, "place_real_fo_exit", lambda *a, **k: {"ok": True, "order_id": "X1"})
    with closing(main.get_db()) as c:
        _insert_leg(c)
        row = c.execute("SELECT * FROM real_fo_positions").fetchone()
        assert main._close_real_fo_option_leg(c, row, "entry SL could not be placed: Kotak state unreadable")
    ev = [e for e in _events() if e["order_id"] == "X1"]
    assert ev and ev[0]["leg"] == "fo_exit"
    assert ev[0]["detail"].startswith("reason: entry SL could not be placed: Kotak state unreadable")


def test_skipped_gate_rows_stay_out_of_order_log():
    with closing(main.get_db()) as c:
        main._log_real_fo_attempt(c, "JIOFIN:CALL", "B", "skipped_spread_too_wide", detail="x")
    assert _events() == []
