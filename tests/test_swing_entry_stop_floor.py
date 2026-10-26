"""B-1367 (2026-10-26): a swing long's entry-day stop is never lowered.

Live: a 23-Oct 15:21 IST CAS-session rejection made _heal_swing_holding_core's fallback recompute and STORE a lower
stop (BANKINDIA 126.73 -> 120.91, WIPRO, COALINDIA), which the 26-Oct 09:15 heal then placed as "carried over"."""
import inspect
import os
import tempfile
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def test_floor_keeps_first_value_and_only_entry_replaces():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        main._swing_entry_stop_record(c, "X.NS", 100.0, "entry", replace=True)
        main._swing_entry_stop_record(c, "X.NS", 90.0, "heal")  # later, lower: ignored
        assert main._swing_entry_stop(c, "X.NS") == 100.0
        assert main._swing_stop_floored(c, "X.NS", 95.0) == 100.0  # never below the entry-day stop
        assert main._swing_stop_floored(c, "X.NS", 110.0) == 110.0  # a trail may still raise it
        main._swing_entry_stop_record(c, "X.NS", 80.0, "new entry", replace=True)
        assert main._swing_entry_stop(c, "X.NS") == 80.0


def test_heal_has_no_lowering_fallback_and_uses_floor():
    src = inspect.getsource(main._heal_swing_holding_core)
    assert "alt < stop" not in src and "UPDATE real_positions_swing SET stop_loss" not in src
    assert "_swing_entry_stop(" in src and "_swing_stop_breached_exit(" in src


def test_heal_carries_floor_not_the_lowered_stop():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                  "stop_loss, sl_trigger_price, strategy) VALUES ('X.NS','X-EQ',1,130,0,'2026-10-09',115.72,120.91,'s')")
        c.commit()
        main._swing_entry_stop_record(c, "X.NS", 126.73, "entry", replace=True)
    placed = {}

    def _ensure(trd, qty, trg):
        placed["trg"] = trg
        return {"ok": True, "order_id": "1", "trigger_price": trg}
    with patch("kotak_real_orders.ensure_resting_sl", side_effect=_ensure), \
            patch("main._swing_live_ltp", return_value=131.0), \
            patch("main._sync_real_positions_swing_external"):
        main._heal_swing_holding_core("X-EQ", {"symbol": "X", "qty": 1, "avg_price": 130.0}, [])
    assert placed["trg"] == 126.73


def _row(c, sym="X.NS"):
    c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
              "stop_loss, sl_order_id, strategy) VALUES (?,'X-EQ',8,134.39,0,'2026-10-09',120.91,'OLD1','s')", (sym,))
    c.commit()


def test_breached_stop_reads_book_cancels_all_sells_then_market_sells():
    """B-1369 owner rule: read the whole Kotak book, cancel the current SL (every open sell), THEN market sell."""
    _fresh_db()
    calls = []
    with main.closing(main.get_db()) as c:
        _row(c)
        with patch("main._kotak_holdings_open_by_trdsym", return_value={"X-EQ": {"qty": 8}}), \
                patch("kotak_real_orders.cancel_all_open_sells",
                      side_effect=lambda t: calls.append("cancel") or {"ok": True, "cancelled": ["OLD1"]}), \
                patch("main._maybe_place_real_swing_exit",
                      side_effect=lambda conn, sym, reason=None: calls.append(("sell", reason))), \
                patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 9, 15, 5)):
            assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 126.32) is True
        r = c.execute("SELECT qty, sl_order_id FROM real_positions_swing WHERE symbol='X.NS'").fetchone()
    assert calls[0] == "cancel" and calls[1][0] == "sell" and "never lowered" in calls[1][1]
    assert r["sl_order_id"] is None and r["qty"] == 8


def test_breach_sends_no_market_sell_while_an_sell_is_still_open():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _row(c)
        with patch("main._kotak_holdings_open_by_trdsym", return_value={"X-EQ": {"qty": 8}}), \
                patch("kotak_real_orders.cancel_all_open_sells", return_value={"ok": False, "remaining": ["OLD1"]}), \
                patch("main._maybe_place_real_swing_exit") as ex, \
                patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 10, 0)):
            assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 126.0) is True
        ex.assert_not_called()


def test_no_breach_action_outside_session_or_above_stop():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _row(c)
        with patch("kotak_real_orders.cancel_all_open_sells") as cx, patch("main._maybe_place_real_swing_exit") as ex:
            with patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 15, 21)):
                assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 126.32) is False  # CAS session
            with patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 10, 0)):
                assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 140.0) is False
        cx.assert_not_called()
        ex.assert_not_called()


def test_cancel_all_open_sells_confirms_book_is_clear():
    import kotak_real_orders as kro
    book = [{"trdSym": "X-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending", "nOrdNo": "1"},
            {"trdSym": "X-EQ", "trnsTp": "S", "prcTp": "L", "ordSt": "open", "nOrdNo": "2"},
            {"trdSym": "X-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "cancelled", "nOrdNo": "3"},
            {"trdSym": "Y-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "open", "nOrdNo": "4"}]
    reads = [book, [dict(r, ordSt="cancelled") if r["nOrdNo"] in ("1", "2") else r for r in book]]

    class _C:
        def order_report(self):
            return {"data": reads.pop(0)}
    with patch("kotak_neo.login", return_value=_C()), \
            patch.object(kro, "cancel_real_order", return_value={"ok": True}) as cr:
        res = kro.cancel_all_open_sells("X-EQ")
    assert res["ok"] and sorted(res["cancelled"]) == ["1", "2"] and cr.call_count == 2


def test_breach_sweep_runs_every_tick():
    src = inspect.getsource(main._scheduler_tick)
    assert "_real_off_loop(_swing_entry_stop_breach_sweep)" in src


def test_backfill_floors_the_stop_and_table_is_mirrored():
    src = inspect.getsource(main._maybe_sync_real_swing_stop_loss)
    assert "_swing_stop_floored(" in src and "_swing_stop_breached_exit(" in src
    assert "swing_entry_stop" in main._GENERIC_MIRROR_TABLES


def test_lost_order_block_state_is_rebuilt_from_daily_bars():
    """B-1364: a held order_block_delta position with no signal_state_swing row gets its exit state back."""
    import pandas as pd
    _fresh_db()
    main._ob_state_last_day = None
    days = pd.bdate_range("2026-08-01", "2026-10-26")
    df = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "Open": 130.0, "High": 133.0, "Low": 127.0,
                       "Close": [130.0 + (i % 5) for i in range(len(days))], "Volume": 1000})
    with main.closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                  "stop_loss, strategy) VALUES ('X.NS','X-EQ',8,134.39,0,'2026-10-09',120.91,'order_block_delta')")
        c.commit()
        main._swing_entry_stop_record(c, "X.NS", 126.73, "entry", replace=True)
        with patch("main.fetch_ohlc", return_value=df), patch("main._sync_signal_state_swing_external"):
            out = main._ensure_order_block_state_for_held(c)
        st = c.execute("SELECT * FROM signal_state_swing WHERE symbol = 'X.NS'").fetchone()
    assert out == [{"symbol": "X.NS", "derived": True}]
    assert st["strategy"] == "order_block_delta" and st["initial_stop_loss"] == 126.73
    assert st["entry_day"] == "2026-10-09" and st["atr_at_entry"] > 0 and st["running_max_close"] == 134.0


def test_swing_mirrors_never_push_before_restore():
    src = inspect.getsource(main._sync_signal_state_swing_external)
    assert "_SWING_MIRROR_HYDRATED" in src and "hydrate_signal_state_swing_from_external()" in src
    src = inspect.getsource(main._sync_real_positions_swing_external)
    assert "_SWING_MIRROR_HYDRATED" in src and "hydrate_real_positions_swing_from_external()" in src
