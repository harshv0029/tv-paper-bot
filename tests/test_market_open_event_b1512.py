"""B-1512: live-tick evidence of an open market, the once-per-session market-open event (protection first), and the
queue of real entries skipped only because the market was closed (persist, replay, drop, expire). No network."""
import datetime as dt
import os
import tempfile
import time
from contextlib import closing

import pytest

import kotak_live_feed as kf
import main

MON_0837 = dt.datetime(2026, 11, 9, 8, 37)
MON_0916 = dt.datetime(2026, 11, 9, 9, 16)
SUN_1100 = dt.datetime(2026, 11, 15, 11, 0)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(kf, "_live_ticks", {})
    monkeypatch.setattr(kf, "on_trade_advance", None)
    main._MARKET_LIVE_CACHE.clear()
    main._MARKET_OPEN_STATE.clear()
    yield
    main._MARKET_LIVE_CACHE.clear()
    main._MARKET_OPEN_STATE.clear()


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    with closing(main.get_db()) as c:
        yield c


def _ist_epoch(d: dt.datetime) -> float:
    return (d - dt.timedelta(minutes=main.IST_OFFSET_MIN)).replace(tzinfo=dt.timezone.utc).timestamp()


def _tick(sym, now, ltt, vol, seg="nse_cm"):
    kf.note_tick(sym, seg, 100.0, sym.split(".")[0] + "-EQ", "1", last_trade_time=ltt, volume_traded_today=vol, now=now)


# ---- 1. tick evidence ---------------------------------------------------------------------------------------------
def test_snapshot_on_subscribe_alone_never_opens():
    now = _ist_epoch(MON_0916)
    for s in ("A.NS", "B.NS", "C.NS"):
        _tick(s, now, now - 5, 1000)  # first tick per symbol = subscribe snapshot
    ev = kf.market_live_evidence("nse", now=now)
    assert ev["open"] is False and ev["count"] == 0


def test_two_symbols_printing_new_trades_open_the_segment():
    now = _ist_epoch(MON_0916)
    for s in ("A.NS", "B.NS"):
        _tick(s, now - 30, now - 35, 1000)
        _tick(s, now, now - 2, 1010)  # volume grew, trade time advanced, both today
    assert kf.market_live_evidence("nse", now=now)["open"] is True
    assert kf.market_live_evidence("mcx", now=now)["open"] is False  # segments are separate
    assert kf.market_live_evidence("nse", now=now + 121)["open"] is False  # evidence ages out after 120 s


def test_one_symbol_or_unchanged_volume_does_not_open():
    now = _ist_epoch(MON_0916)
    _tick("A.NS", now - 30, now - 35, 1000)
    _tick("A.NS", now, now - 2, 1010)
    _tick("B.NS", now - 30, now - 35, 500)
    _tick("B.NS", now, now - 35, 500)  # repeat of the same print
    assert kf.market_live_evidence("nse", now=now)["open"] is False


def test_preopen_first_print_and_stale_reconnect_snapshot_do_not_count():
    now = _ist_epoch(MON_0916)
    yday = now - 86400
    for s in ("A.NS", "B.NS"):
        _tick(s, now - 60, yday, 1000)      # yesterday's last print
        _tick(s, now, now - 10, 50)         # first print of today (pre-open equilibrium): baseline is yesterday
    assert kf.market_live_evidence("nse", now=now)["open"] is False
    for s in ("C.NS", "D.NS"):
        _tick(s, now - 60, now - 4000, 1000)
        _tick(s, now, now - 3990, 1200)     # today but > 300 s old (a reconnect snapshot of old prints)
    assert kf.market_live_evidence("nse", now=now)["open"] is False


def test_exchange_1980_epoch_is_normalised():
    now = _ist_epoch(MON_0916)
    nse_ltt = int(now - 3 - kf._NSE_EPOCH_OFFSET)
    assert abs(kf._ltt_epoch(nse_ltt) - (now - 3)) < 1
    assert abs(kf._ltt_epoch((now - 3) * 1000) - (now - 3)) < 1


# ---- 2. gates: tick evidence opens only an unlisted (non-regular) day ---------------------------------------------
def test_sunday_with_tick_evidence_opens_every_nse_gate(monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: SUN_1100)
    monkeypatch.setattr(main, "_market_live_open", lambda seg="nse": seg == "nse")
    assert main._tick_open_override(None, "nse") is True
    assert main.is_nse_trading_day("2026-11-15") is True  # today (no-arg form is pinned by conftest)
    assert main.is_nse_trading_day("2026-11-14") is False  # another closed day never uses today's ticks
    assert main._nse_closed_day(SUN_1100, "RELIANCE.NS") is False
    assert main._nse_closed_day(SUN_1100, "AAPL") is True  # US never opens through NSE ticks
    aware = SUN_1100.replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    assert main._exchange_purge_window(aware) is False
    late = aware.replace(hour=15, minute=20)
    monkeypatch.setattr(main, "ist_now", lambda: late.replace(tzinfo=None))
    assert main._exchange_purge_window(late) is True  # 15:15+ CAS: never an SL placement
    monkeypatch.setattr(main, "_tick_open_override", lambda *a, **k: True)
    assert main._nse_equity_market_open_now() is True


def test_sunday_without_evidence_stays_closed_and_regular_weekday_ignores_ticks(monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: SUN_1100)
    monkeypatch.setattr(main, "_market_live_open", lambda seg="nse": False)
    assert main._tick_open_override(None, "nse") is False
    assert main.is_nse_trading_day("2026-11-15") is False
    monkeypatch.setattr(main, "ist_now", lambda: MON_0837)
    monkeypatch.setattr(main, "_market_live_open", lambda seg="nse": True)
    assert main._tick_open_override(None, "nse") is False  # weekday pre-open prints never open entries


def test_past_now_local_never_uses_todays_ticks(monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: SUN_1100)
    monkeypatch.setattr(main, "_market_live_open", lambda seg="nse": True)
    assert main._tick_open_override(SUN_1100 - dt.timedelta(days=7), "nse") is False


# ---- 3. market-open event ------------------------------------------------------------------------------------------
def test_event_fires_once_protection_before_replay_and_is_durable(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0916)
    monkeypatch.setattr(main, "_segment_open_now", lambda seg: seg == "nse")
    order = []
    protect = lambda: order.append("protect") or {"ok": True}  # noqa: E731
    replay = lambda conn, force=False: order.append("replay") or {"placed": 0}  # noqa: E731
    assert main._market_open_event_check(db, protect=protect, replay=replay) == ["nse"]
    assert order[:2] == ["protect", "replay"]
    assert main._market_open_event_check(db, protect=protect, replay=replay) == []
    assert order.count("protect") == 1
    rows = db.execute("SELECT symbol, detail FROM real_order_events WHERE event = 'market_open_event'").fetchall()
    assert len(rows) == 1 and rows[0][0] == "MARKET:NSE" and rows[0][1].startswith("reason: NSE market opened")
    main._MARKET_OPEN_STATE.clear()  # simulated restart mid-session
    assert main._market_open_event_check(db, protect=protect, replay=replay) == []
    assert order.count("protect") == 1


def test_event_waits_for_the_closed_to_open_transition(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0837)
    state = {"open": False}
    monkeypatch.setattr(main, "_segment_open_now", lambda seg: seg == "nse" and state["open"])
    calls = []
    p = lambda: calls.append("p") or {}  # noqa: E731
    r = lambda conn, force=False: {}  # noqa: E731
    assert main._market_open_event_check(db, protect=p, replay=r) == []
    state["open"] = True
    assert main._market_open_event_check(db, protect=p, replay=r) == ["nse"]
    assert calls == ["p"]


# ---- 4. pending-trigger queue --------------------------------------------------------------------------------------
def _paper_swing(db, sym="TCS.NS", entry=100.0, stop=95.0, strat="gap_and_go"):
    db.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
               "entry_ts) VALUES (?, ?, '2026-11-09', ?, ?, 3, 0)", (sym, strat, entry, stop))
    db.commit()


def test_market_closed_skip_is_queued_and_mirrored(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0837)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_swing_real_entry_session_open", lambda: False)
    monkeypatch.setattr(main, "_select_swing_exit_variant", lambda *a, **k: None)
    main._maybe_place_real_swing_entry(db, "TCS.NS", 3, 100.0, 95.0, "gap_and_go")
    main._maybe_place_real_swing_entry(db, "TCS.NS", 4, 101.0, 96.0, "gap_and_go")  # re-fire refreshes levels
    rows = db.execute("SELECT session_day, engine, symbol, strategy, entry_price, stop_loss, qty, status "
                      "FROM pending_open_triggers").fetchall()
    assert [tuple(r) for r in rows] == [("2026-11-09", "swing", "TCS.NS", "gap_and_go", 101.0, 96.0, 4, "queued")]
    assert "pending_open_triggers" in main._GENERIC_MIRROR_TABLES
    assert "pending_open_triggers" in main._GENERIC_MIRROR_UPSTASH_TABLES


def test_queue_survives_a_simulated_wipe(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    monkeypatch.setattr(main, "ist_now", lambda: MON_0837)
    for _ in range(2):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        monkeypatch.setattr(main, "DB_PATH", path)
        main.init_db()
        main._generic_mirror_hydrated.clear()
        main.hydrate_generic_tables_from_external(only=("pending_open_triggers",))
        with closing(main.get_db()) as c:
            if not c.execute("SELECT 1 FROM pending_open_triggers").fetchone():
                main._queue_open_trigger(c, "swing", "TCS.NS", "gap_and_go", 100.0, 95.0, None, 3)
                main.sync_generic_tables_external(only=("pending_open_triggers",))
            else:
                assert c.execute("SELECT symbol, status FROM pending_open_triggers").fetchall()[0][:] == \
                    ("TCS.NS", "queued")
                return
    pytest.fail("queue row was not restored after the wipe")


def _open_now(monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0916)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    main._MARKET_OPEN_STATE["nse"] = {"open": True, "fired_day": "2026-11-09", "fired_at": time.time()}


def test_replay_places_through_the_swing_engine(db, monkeypatch):
    _open_now(monkeypatch)
    _paper_swing(db)
    main._queue_open_trigger(db, "swing", "TCS.NS", "gap_and_go", 100.0, 95.0, None, 3)
    calls = []

    def fake_entry(conn, sym, qty, entry, stop, strat):
        calls.append((sym, qty, entry, stop, strat))
        main._log_real_attempt(conn, sym, "B", "confirmed", qty=1, strategy=strat)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", fake_entry)
    out = main._replay_open_triggers(db)
    assert out["placed"] == 1 and calls == [("TCS.NS", 3, 100.0, 95.0, "gap_and_go")]
    assert db.execute("SELECT status FROM pending_open_triggers").fetchone()[0] == "placed"
    ev = db.execute("SELECT event, detail FROM real_order_events WHERE symbol = 'TCS.NS'").fetchall()
    assert ev[-1][0] == "queued_trigger_placed" and ev[-1][1].startswith("reason: ")
    funnel = main._queued_at_open_summary(db, "2026-11-09")
    assert funnel["placed"] == 1 and funnel["by_engine"] == {"swing": {"placed": 1}}


def test_replay_drops_a_gap_through_stop_via_the_real_engine(db, monkeypatch):
    _open_now(monkeypatch)
    _paper_swing(db, entry=100.0, stop=95.0)
    main._queue_open_trigger(db, "swing", "TCS.NS", "gap_and_go", 100.0, 95.0, None, 3)
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_swing_real_entry_session_open", lambda: True)
    monkeypatch.setattr(main, "_select_swing_exit_variant", lambda *a, **k: None)
    monkeypatch.setattr(main, "_maybe_place_swing_option_leg", lambda *a, **k: None)
    monkeypatch.setattr(main, "_etf_entry_range_ok", lambda s: (True, ""))
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "_sector_cap_blocks", lambda *a, **k: None)
    monkeypatch.setattr(main, "_kotak_sold_today", lambda *a, **k: False)
    monkeypatch.setattr(kf, "get_live_ticks", lambda: {"TCS.NS": {"ltp": 94.0, "trading_symbol": "TCS-EQ"}})
    out = main._replay_open_triggers(db)
    assert out["dropped"] == 1
    st, outcome = db.execute("SELECT status, outcome FROM pending_open_triggers").fetchone()
    assert st == "dropped" and outcome.startswith("skipped_stop_not_below_price")
    assert main._queued_at_open_summary(db, "2026-11-09")["drop_reasons"] == {"skipped_stop_not_below_price": 1}


def test_transient_skip_stays_queued_and_replay_needs_the_open_event(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0916)
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    _paper_swing(db)
    main._queue_open_trigger(db, "swing", "TCS.NS", "gap_and_go", 100.0, 95.0, None, 3)
    hits = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry",
                        lambda conn, sym, *a: hits.append(sym) or main._log_real_attempt(
                            conn, sym, "B", "skipped_no_live_tick"))
    assert main._replay_open_triggers(db)["skipped"].startswith("no NSE open event")  # protection first
    assert hits == []
    main._MARKET_OPEN_STATE["nse"] = {"open": True, "fired_day": "2026-11-09", "fired_at": time.time()}
    assert main._replay_open_triggers(db)["requeued"] == 1
    assert db.execute("SELECT status FROM pending_open_triggers").fetchone()[0] == "queued"
    assert main._open_trigger_symbols_queued(db) == {"TCS.NS"}  # the all-day retry leaves it to the queue
    main._MARKET_OPEN_STATE["nse"]["fired_at"] = time.time() - 31 * 60
    assert main._replay_open_triggers(db)["skipped"].startswith("past open")
    assert main._open_trigger_symbols_queued(db) == set()


def test_unplaced_triggers_expire_when_the_session_ends(db, monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: MON_0916)
    main._queue_open_trigger(db, "swing", "TCS.NS", "gap_and_go", 100.0, 95.0, None, 3)
    db.execute("INSERT INTO pending_open_triggers (session_day, engine, symbol, strategy, status) "
               "VALUES ('2026-11-06', 'swing', 'OLD.NS', 'gap_and_go', 'queued')")
    db.commit()
    assert main._expire_open_triggers(db) == 1  # the older session only
    main._MARKET_OPEN_STATE["nse"] = {"open": False, "fired_day": "2026-11-09", "fired_at": time.time() - 7 * 3600}
    assert main._expire_open_triggers(db) == 1  # today's session opened and has closed again
    st = dict(db.execute("SELECT symbol, status FROM pending_open_triggers").fetchall())
    assert st == {"TCS.NS": "expired", "OLD.NS": "expired"}
    assert db.execute("SELECT COUNT(*) FROM real_order_events WHERE event = 'queued_trigger_expired'").fetchone()[0] == 2


def test_feed_wake_starts_the_detector_only_when_not_fired(monkeypatch):
    monkeypatch.setattr(main, "ist_now", lambda: SUN_1100)
    monkeypatch.setattr(main, "_segment_open_now", lambda seg: True)
    started = []
    monkeypatch.setattr(main, "_market_open_event_check_own_conn", lambda: started.append(1))
    main._market_open_wake_last.clear()
    main._on_feed_trade_advance("nse")
    time.sleep(0.05)
    assert started == [1]
    main._MARKET_OPEN_STATE["nse"] = {"open": True, "fired_day": "2026-11-15", "fired_at": time.time()}
    main._market_open_wake_last.clear()
    main._on_feed_trade_advance("nse")
    time.sleep(0.05)
    assert started == [1]
