"""B-1544 (user 2026-11-10): news stop starts 3% from entry, then trails 0.5% of ENTRY behind the best price."""
import time
from contextlib import closing
from unittest.mock import patch

import main
from tests.test_news_trades_b1541 import BAD2, GOOD2, _agg, _conn, _open
from tests.test_swing_ltp_trail_and_nykaa import _db

TAG = main.NEWS_TRADE_TAGS["long"]


def test_trail_level_is_pure_and_only_tightens():
    f = main._news_trail_stop
    assert f("long", 1000.0, 970.0, 1000.0) == 970.0      # not past entry yet: the 3% stop stands
    assert f("long", 1000.0, 970.0, 1010.0) == 1005.0     # 0.5% of entry (Rs5) behind the peak
    assert f("long", 1000.0, 1005.0, 1003.0) == 1005.0    # never loosens
    assert f("short", 1000.0, 1030.0, 1000.0) == 1030.0
    assert f("short", 1000.0, 1030.0, 990.0) == 995.0
    assert f("short", 1000.0, 995.0, 998.0) == 995.0


def test_paper_long_ratchets_then_stops_out_on_the_trailed_level():
    c, t = _conn(), time.time()
    main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 100.0)
    assert _open(c)["stop_price"] == 97.0
    main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 102.0)
    assert _open(c)["stop_price"] == 101.5
    main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 101.8)   # dips but above the stop: stop unchanged
    assert _open(c)["stop_price"] == 101.5 and _open(c)["status"] == "open"
    assert main._news_trades_step(c, "XYZ.NS", _agg(GOOD2), t, 101.4) == [("XYZ.NS", "long", "close")]
    r = _open(c)
    assert r["close_reason"].startswith("stop hit") and r["pnl_pct"] == 0.6  # +1.4% - 0.8% cost


def test_paper_short_mirror():
    c, t = _conn(), time.time()
    main._news_trades_step(c, "XYZ.NS", _agg(BAD2), t, 100.0)
    main._news_trades_step(c, "XYZ.NS", _agg(BAD2), t, 98.0)
    assert _open(c, "short")["stop_price"] == 98.5
    assert main._news_trades_step(c, "XYZ.NS", _agg(BAD2), t, 98.6) == [("XYZ.NS", "short", "close")]


def _seed_news(conn, entry_day="2026-11-09"):
    conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                 "stop_loss, strategy, sl_order_id, sl_trigger_price) VALUES ('XYZ.NS', 'XYZ-EQ', 1, 1000.0, 1.0, ?, 970.0, ?, 'o1', 970.0)",
                 (entry_day, TAG))
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, qty, "
                 "entry_ts, fx_to_inr) VALUES ('XYZ.NS', ?, ?, 1000.0, 970.0, NULL, 1, 1.0, 1.0)", (TAG, entry_day))
    conn.commit()


def _run(conn, ltp, day_peak, ens):
    with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
         patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"XYZ-EQ": {"qty": 1}}), \
         patch.object(main, "_swing_live_ltp_peak", return_value=(ltp, day_peak)), \
         patch("kotak_real_orders.ensure_resting_sl", side_effect=ens):
        return main._sync_swing_ltp_trail(conn)


def test_real_resting_sl_trails_half_percent_of_entry_behind_peak():
    _db()
    calls = []
    def ens(trd, qty, trg):
        calls.append(trg)
        return {"ok": True, "order_id": "o2", "trigger_price": trg, "action": "replaced"}
    with closing(main.get_db()) as conn:
        _seed_news(conn)
        assert _run(conn, 999.0, 999.0, ens) == [] and calls == []          # not past entry: 3% stop stays
        a = _run(conn, 1019.0, 1020.0, ens)
        assert calls == [1015.0] and a[0]["ok"]                              # peak 1020 - Rs5
        assert _run(conn, 1017.0, 1018.0, ens) == [] and calls == [1015.0]   # never lowered
        ev = conn.execute("SELECT detail FROM real_order_events WHERE detail LIKE '%news trail%'").fetchone()[0]
        assert "news trail" in ev


def test_entry_day_ignores_a_day_high_from_before_the_entry():
    _db()
    calls = []
    def ens(trd, qty, trg):
        calls.append(trg)
        return {"ok": True, "order_id": "o2", "trigger_price": trg, "action": "replaced"}
    with closing(main.get_db()) as conn:
        _seed_news(conn, entry_day=main.ist_now().strftime("%Y-%m-%d"))
        assert _run(conn, 1002.0, 1040.0, ens) == [{"symbol": "XYZ.NS", "ok": True, "from": 970.0, "to": 997.0}]
        assert conn.execute("SELECT peak_ltp FROM swing_ltp_peak").fetchone()[0] == 1002.0


def test_price_already_through_the_trail_sells_now():
    _db()
    with closing(main.get_db()) as conn:
        _seed_news(conn)
        with patch.object(main, "_news_real_close", return_value=True) as close:
            a = _run(conn, 1010.0, 1020.0, lambda *a: (_ for _ in ()).throw(AssertionError("no SL replace")))
        assert a[0]["news_trail_exit"] and "trail stop hit" in close.call_args[0][3]


# ---- B-1545: a stale or after-hours tick is not a live tick (LENSKART opened on paper at 15:45 IST) ----
def _ticks(**kw):
    import kotak_live_feed
    return patch.object(kotak_live_feed, "get_live_ticks", return_value={"LENSKART.NS": kw})


def test_news_tick_must_be_in_session_and_fresh():
    now = time.time()
    with patch.object(main, "_swing_real_entry_session_open", return_value=False), _ticks(ltp=718.8, last_trade_epoch=now):
        assert main._news_live_ltp("LENSKART.NS", now) == 0.0          # after the close: never live
    with patch.object(main, "_swing_real_entry_session_open", return_value=True):
        with _ticks(ltp=718.8, last_trade_epoch=now - 3600):
            assert main._news_live_ltp("LENSKART.NS", now) == 0.0      # last trade an hour ago: stale
        with _ticks(ltp=718.8, last_trade_epoch=now - 30):
            assert main._news_live_ltp("LENSKART.NS", now) == 718.8
        with _ticks(ltp=718.8, updated_at_utc=now - 10):
            assert main._news_live_ltp("LENSKART.NS", now) == 718.8    # no trade time: receipt time counts
        with _ticks():
            assert main._news_live_ltp("LENSKART.NS", now) == 0.0


def test_after_hours_good_news_opens_nothing():
    c = _conn()
    with patch.object(main, "_swing_real_entry_session_open", return_value=False), \
         _ticks(ltp=718.8, last_trade_epoch=time.time()):
        assert main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), time.time(),
                                      main._news_live_ltp("LENSKART.NS")) == []
    assert c.execute("SELECT COUNT(*) FROM news_trades").fetchone()[0] == 0


# ---- B-1546: a paper long opened outside the session is re-based and bought for real while news is still confirmed ----
def test_stale_paper_long_is_rebased_into_a_real_buy_only_while_news_is_confirmed():
    import datetime as dt
    holiday_1545 = (dt.datetime(2026, 11, 10, 15, 45) - dt.timedelta(minutes=330)).replace(tzinfo=dt.timezone.utc).timestamp()
    assert main._news_opened_outside_session(holiday_1545)
    assert not main._news_opened_outside_session(
        (dt.datetime(2026, 11, 11, 10, 0) - dt.timedelta(minutes=330)).replace(tzinfo=dt.timezone.utc).timestamp())
    from tests.test_news_trades_b1541 import CALM
    c, t = _conn(), time.time()
    c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price) VALUES "
              "('LENSKART.NS', 'long', ?, ?, 718.8, 697.24)", (TAG, holiday_1545))
    with patch.object(main, "_news_real_open", return_value=False) as ro:
        main._news_trades_step(c, "LENSKART.NS", _agg(CALM), t, 730.0)   # news no longer confirmed: no rebase
        ro.assert_not_called()
    c.execute("UPDATE news_trades SET status = 'open', close_ts = NULL WHERE id = 1")
    with patch.object(main, "_news_real_open", return_value=True) as ro, \
            patch.object(main, "_news_late_entry_ok", return_value=True):  # B-1551 gate tested separately
        acts = main._news_trades_step(c, "LENSKART.NS", _agg(GOOD2), t, 730.0)
    assert acts == [("LENSKART.NS", "long", "rebase"), ("LENSKART.NS", "long", "real_open")]
    assert ro.call_args[0][3] == 730.0 and ro.call_args[0][4] == 708.1
    old, new = c.execute("SELECT * FROM news_trades ORDER BY id").fetchall()[:2]
    assert old["status"] == "closed" and old["close_reason"].startswith("re-based")
    assert new["status"] == "open" and new["entry_price"] == 730.0
