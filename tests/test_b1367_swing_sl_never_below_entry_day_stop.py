"""B-1367 (27-Oct 2026 09:15 IST, owner rule: a swing trade's 09:15 SL keeps the entry-day stop and is never lowered):
Kotak showed SELL SLs with no app log row BELOW the entry-day stop - BANKINDIA 115.72 (order 261027000011646, entry
stop 126.73), COALINDIA 373.20 (398.35), GSEC5IETF 63.93 (64.70). One test per swing SL path: every path ends at
kotak_real_orders' chokepoint floor, the provider now finds the floor even when the swing row is missing or the
holding sits in the intraday table, the align step no longer adopts a below-floor live SL as the row's protection,
and ensure_resting_sl's restore of a just-cancelled stop is never floored into a refused (naked) order."""
import time
from contextlib import closing

import pytest

import kotak_real_orders as kro
import main


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_swing_external", "_sync_signal_state_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    return tmp_path


def _swing_paper(c, sym="BANKINDIA.NS", entry=130.0, init_stop=126.73):
    c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
              "entry_ts) VALUES (?, 'gap_and_go', '2026-10-21', ?, ?, 8, ?)", (sym, entry, init_stop, time.time()))


def _swing_real(c, sym="BANKINDIA.NS", trd="BANKINDIA-EQ", stop=115.72, sl_oid=None, sl_trg=None):
    c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
              "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES (?,?,8,130.0,0,'2026-10-21',?,?,?,'gap_and_go')",
              (sym, trd, stop, sl_oid, sl_trg))


# ------------------------------------------------------------------ provider (the central chokepoint's floor source)

def test_provider_floors_a_swing_holding_whose_swing_row_was_lost(db):
    """Upstash-restore gap: signal_state_swing survived, real_positions_swing did not -> floor still known."""
    with closing(main.get_db()) as c:
        _swing_paper(c)
        c.commit()
    assert main._real_stop_floor_for_trdsym("BANKINDIA-EQ", "long") == 126.73


def test_provider_floors_a_swing_holding_misadopted_into_the_intraday_table(db):
    with closing(main.get_db()) as c:
        _swing_paper(c, "COALINDIA.NS", 410.0, 398.35)
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                  "VALUES ('COALINDIA.NS','COALINDIA-EQ',1,410.0,0,'2026-10-21')")
        c.execute("INSERT INTO swing_entry_stop (symbol, entry_stop, set_at, source) VALUES ('COALINDIA.NS',398.35,0,'t')")
        c.commit()
    assert main._real_stop_floor_for_trdsym("COALINDIA-EQ", "long") == 398.35


def test_provider_ignores_swing_record_for_a_symbol_the_swing_engine_does_not_own(db):
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                  "VALUES ('GSEC5IETF.NS','GSEC5IETF-EQ',2,66.0,0,'2026-11-02')")
        c.execute("INSERT INTO swing_entry_stop (symbol, entry_stop, set_at, source) VALUES ('GSEC5IETF.NS',64.70,0,'old')")
        c.commit()
    assert main._real_stop_floor_for_trdsym("GSEC5IETF-EQ", "long") is None
    assert main._nse_symbol_from_trdsym("GSEC5IETF-EQ") == "GSEC5IETF.NS"


def test_chokepoint_raises_the_27oct_bankindia_send(db, monkeypatch):
    """place_real_stop_loss('BANKINDIA-EQ', 115.72) with the swing row lost -> Kotak gets 126.73."""
    with closing(main.get_db()) as c:
        _swing_paper(c)
        c.commit()
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", main._real_stop_floor_for_trdsym)
    monkeypatch.setattr(kro, "_band_reference", lambda t: (131.0, 132.0))
    monkeypatch.setattr(kro, "_tick_size_for", lambda t: 0.01)
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    sent = []
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    res = kro.place_real_stop_loss("BANKINDIA-EQ", 8, 115.72)
    kro._RECENT_SL_PLACED.pop("BANKINDIA-EQ", None)
    assert sent == [126.73] and res["entry_floor_raised_from"] == 115.72


# ------------------------------------------------------------------ ensure_resting_sl restore (no naked position)

def test_restore_after_failed_replace_resends_the_old_stop_unfloored(monkeypatch):
    book = [{"trdSym": "BANKINDIA-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending", "nOrdNo": "OLD",
             "trgPrc": "119.97", "qty": "8"}]

    class _C:
        def order_report(self):
            return {"data": book}
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C())
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", lambda t, s: 126.73)
    monkeypatch.setattr(kro, "_band_reference", lambda t: (None, None))
    monkeypatch.setattr(kro, "_tick_size_for", lambda t: 0.01)
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: {"ok": True})
    sent = []

    def _once(trd, q, t):
        sent.append(t)
        if abs(t - 126.73) < 1e-6:
            return {"ok": False, "detail": "RMS reject", "order_id": None}
        return {"ok": True, "order_id": "RESTORED", "trigger_price": t}
    monkeypatch.setattr(kro, "_place_real_stop_loss_once", _once)
    kro._RECENT_SL_PLACED.pop("BANKINDIA-EQ", None)
    res = kro.ensure_resting_sl("BANKINDIA-EQ", 8, 115.72)
    kro._RECENT_SL_PLACED.pop("BANKINDIA-EQ", None)
    assert res["action"] == "replace_failed" and res["restored_order_id"] == "RESTORED"
    assert sent == [126.73, 119.97]  # floored attempt first; the restore is the exact old stop, not a 2nd refusal
    assert not getattr(kro._FLOOR_BYPASS, "on", False)


# ------------------------------------------------------------------ align step (do not adopt a below-floor live SL)

def _book(trg):
    return [{"trdSym": "BANKINDIA-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending",
             "nOrdNo": "261027000011646", "trgPrc": str(trg), "qty": "8"}]


def test_align_does_not_adopt_a_live_sl_below_the_entry_day_stop(db, monkeypatch):
    monkeypatch.setattr(kro, "_band_reference", lambda t: (131.0, 132.0))
    with closing(main.get_db()) as c:
        _swing_paper(c)
        _swing_real(c)
        c.execute("INSERT INTO swing_entry_stop (symbol, entry_stop, set_at, source) VALUES ('BANKINDIA.NS',126.73,0,'t')")
        c.commit()
        out = main._align_swing_sl_rows_to_kotak(c, _book(115.72))
        row = c.execute("SELECT sl_order_id, sl_trigger_price FROM real_positions_swing").fetchone()
        ev = c.execute("SELECT order_id, detail FROM real_order_events WHERE event='below_entry_day_stop'").fetchone()
    assert out[0]["action"] == "below_entry_day_stop" and row[0] is None and row[1] == 115.72
    assert ev[0] == "261027000011646" and ev[1].startswith("reason:")


def test_align_keeps_the_lower_live_sl_when_the_floor_cannot_rest(db, monkeypatch):
    monkeypatch.setattr(kro, "_band_reference", lambda t: (127.0, 126.32))  # 26-Oct: last 126.32 < 126.73
    with closing(main.get_db()) as c:
        _swing_paper(c)
        _swing_real(c)
        c.commit()
        main._align_swing_sl_rows_to_kotak(c, _book(119.97))
        row = c.execute("SELECT sl_order_id, sl_trigger_price FROM real_positions_swing").fetchone()
    assert row[0] == "261027000011646" and row[1] == 119.97


def test_align_adopts_a_live_sl_at_or_above_the_floor(db, monkeypatch):
    monkeypatch.setattr(kro, "_band_reference", lambda t: (131.0, 132.0))
    with closing(main.get_db()) as c:
        _swing_paper(c)
        _swing_real(c)
        c.commit()
        main._align_swing_sl_rows_to_kotak(c, _book(127.5))
        row = c.execute("SELECT sl_order_id, sl_trigger_price FROM real_positions_swing").fetchone()
    assert row[0] == "261027000011646" and row[1] == 127.5


# ------------------------------------------------------------------ per-tick swing retry + reroute

def test_per_tick_swing_retry_places_the_floored_stop_with_a_reason(db, monkeypatch):
    import kotak_live_feed
    monkeypatch.setattr(main, "_exchange_purge_window", lambda: False)
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 132.0)
    monkeypatch.setattr(kotak_live_feed, "get_live_ticks", lambda: {"BANKINDIA.NS": {"ltp": 132.0}})
    sent = []
    monkeypatch.setattr(kro, "ensure_resting_sl",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "N", "trigger_price": t,
                                                             "action": "placed"})
    with closing(main.get_db()) as c:
        _swing_paper(c)
        _swing_real(c)
        c.commit()
        main._maybe_sync_real_swing_stop_loss(c)
        ev = c.execute("SELECT detail FROM real_order_events WHERE leg='sl' AND order_id='N'").fetchone()
    assert sent == [126.73] and ev and ev[0].startswith("reason:")


def test_reroute_never_stores_a_previous_day_stop_below_the_entry_day_stop(db):
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day) "
                  "VALUES ('BANKINDIA.NS','BANKINDIA-EQ',8,130.0,1.0,'2026-10-27')")
        c.execute("INSERT INTO swing_entry_stop (symbol, entry_stop, set_at, source) VALUES ('BANKINDIA.NS',126.73,0,'t')")
        main._log_real_order_event(c, "BANKINDIA.NS", "sl", "placed", new_state="resting SELL trigger Rs115.72")
        c.commit()
        row = c.execute("SELECT * FROM real_positions WHERE symbol='BANKINDIA.NS'").fetchone()
        assert main._reroute_orphan_intraday_to_swing(c, row)
        sw = c.execute("SELECT stop_loss FROM real_positions_swing").fetchone()
        st = c.execute("SELECT initial_stop_loss FROM signal_state_swing").fetchone()
        ev = c.execute("SELECT new_state, detail FROM real_order_events WHERE event='moved_to_swing'").fetchone()
    assert sw[0] == 126.73 and st[0] == 126.73
    assert "126.73" in ev[0] and ev[1].startswith("reason:")
