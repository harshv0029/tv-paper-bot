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


def test_breached_stop_exits_at_market_in_session_instead_of_lowering():
    _fresh_db()
    with main.closing(main.get_db()) as c, \
            patch("main._maybe_place_real_swing_exit") as ex, \
            patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 9, 15, 5)):
        assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 126.32) is True
        ex.assert_called_once()
        assert "never lowered" in ex.call_args.kwargs["reason"]
    with main.closing(main.get_db()) as c, patch("main._maybe_place_real_swing_exit") as ex, \
            patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 15, 21)):
        assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 126.32) is False  # CAS session: no market sell
        ex.assert_not_called()
    with main.closing(main.get_db()) as c, patch("main._maybe_place_real_swing_exit") as ex, \
            patch("main.ist_now", return_value=main.dt.datetime(2026, 10, 27, 10, 0)):
        assert main._swing_stop_breached_exit(c, "X.NS", 126.73, 140.0) is False
        ex.assert_not_called()


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
