"""B-1381 (2026-10-27): real swing holdings opened by a 1h long cell lost their signal_state_swing row.

Live: GSEC5IETF.NS entered 2026-10-16 11:29 IST via macddiv__hist_any__long__1h__atr3_w5__nonovl__v2; ~95 s later a
restarted process logged 'paper swing row is missing' every day since. Root cause: no swing ENTRY path pushed
signal_state_swing to the Upstash mirror (only exits/heals and one daily push did), so a restart before the next push
restored the real row but not the paper exit state, and the 1h engine never evaluated the cell's own exit again."""
import datetime as dt
import inspect
import os
import tempfile
from unittest.mock import patch

import pandas as pd

import main

TAG = "macddiv__hist_any__long__1h__atr3_w5__nonovl__v2"
SYM, TRD = "GSEC5IETF.NS", "GSEC5IETF-EQ"


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._orphan_1h_state_last_day = None


def _ist_epoch(s):
    return (dt.datetime.strptime(s, "%Y-%m-%d %H:%M") - dt.timedelta(minutes=main.IST_OFFSET_MIN)).replace(
        tzinfo=dt.timezone.utc).timestamp()


OPENED_AT = _ist_epoch("2026-10-16 11:29")


def _hourly(days, low=65.0, breach_after=None):
    rows = []
    for d in days:
        for h in ("09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"):
            stamp = f"{d} {h}"
            lo = 64.0 if breach_after and stamp > breach_after else low
            rows.append({"Date": pd.Timestamp(stamp), "Open": 65.5, "High": 66.0, "Low": lo, "Close": 65.5,
                         "Volume": 1000})
    return pd.DataFrame(rows)


DAYS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", "2026-10-19")]


def _real_row(c, strategy=TAG, stop=64.70, opened_at=OPENED_AT):
    c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
              "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES (?, ?, 2, 65.50, ?, '2026-10-16', ?, "
              "'SL1', ?, ?)", (SYM, TRD, opened_at, stop, stop, strategy))
    c.commit()


def _rebuild(c, held=True, df=None):
    holdings = {TRD: {"qty": 2, "avg_price": 65.5, "symbol": SYM}} if held else {}
    with patch("main._kotak_holdings_open_by_trdsym", return_value=holdings), \
            patch("main._kotak_symbol_still_open", return_value=False), \
            patch("main._sync_signal_state_swing_external") as sync, \
            patch("main._maybe_place_real_swing_exit") as ex, \
            patch("kotak_real_orders.ensure_resting_sl") as sl:
        out = main._ensure_1h_swing_state_for_orphans(c, fetch=lambda *a, **k: df if df is not None else _hourly(DAYS))
    return out, sync, ex, sl


def test_orphan_macddiv_row_is_rebuilt_without_any_order():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        out, sync, ex, sl = _rebuild(c)
        st = c.execute("SELECT * FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
        pos = c.execute("SELECT qty FROM positions WHERE symbol = ?", (SYM,)).fetchone()
        real = c.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", (SYM,)).fetchone()
    assert out == [{"symbol": SYM, "derived": True, "entry_day": "2026-10-16 10:15", "stop": 64.70}]
    assert st["strategy"] == TAG and st["entry_day"] == "2026-10-16 10:15"
    assert st["entry_price"] == 65.50 and st["initial_stop_loss"] == 64.70 and st["qty"] == 2
    assert pos["qty"] == 2  # the paper exit has a position to close
    assert sync.called  # Upstash durability of the rebuilt row
    ex.assert_not_called()  # a missing row is never an exit/stop decision
    sl.assert_not_called()
    assert real["sl_order_id"] == "SL1" and real["sl_trigger_price"] == 64.70 and real["stop_loss"] == 64.70


def test_entry_day_stop_is_preferred_over_row_stop():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, stop=64.90)
        main._swing_entry_stop_record(c, SYM, 64.70, "entry", replace=True)
        _rebuild(c)
        st = c.execute("SELECT initial_stop_loss FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
    assert st["initial_stop_loss"] == 64.70


def test_not_held_at_kotak_is_not_rebuilt():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        out, *_ = _rebuild(c, held=False)
        assert c.execute("SELECT 1 FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone() is None
    assert out == [{"symbol": SYM, "derived": False, "why": "not held at Kotak"}]


def test_kotak_unknown_skips_and_retries_next_tick():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        with patch("main._kotak_holdings_open_by_trdsym", return_value=None):
            assert main._ensure_1h_swing_state_for_orphans(c, fetch=lambda *a, **k: _hourly(DAYS)) == []
        assert main._orphan_1h_state_last_day is None
        assert c.execute("SELECT 1 FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone() is None


def test_unknown_strategy_or_bad_stop_is_never_invented():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, strategy="some_daily_cell")
        out, *_ = _rebuild(c)
        assert c.execute("SELECT 1 FROM signal_state_swing").fetchone() is None
        assert out[0]["derived"] is False
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, stop=0)
        out, *_ = _rebuild(c)
        assert c.execute("SELECT 1 FROM signal_state_swing").fetchone() is None
        assert out == [{"symbol": SYM, "derived": False, "why": "entry bar/stop not derivable"}]


def test_existing_paper_row_is_left_untouched():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                  "entry_ts) VALUES (?, ?, '2026-10-16 10:15', 65.5, 64.0, 2, 0)", (SYM, TAG))
        c.commit()
        out, *_ = _rebuild(c)
        st = c.execute("SELECT initial_stop_loss FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
    assert out == [] and st["initial_stop_loss"] == 64.0


def _run_1h_pass(c, df):
    with patch("main._maybe_place_real_swing_exit") as ex, patch("main._sync_signal_state_swing_external"):
        main._run_long_swing_1h_pass(c, [SYM], 100000.0, "2026-10-19", set(), fetch=lambda *a, **k: df)
    return ex


def test_rebuilt_row_is_governed_by_its_own_1h_exit_rule():
    """Owning engine evaluates the cell's own exit: no exit while inside stop and hold; stop breach -> paper exit
    with the strategy's reason, then the real exit mirror."""
    days = [d for d in DAYS if d <= "2026-10-19"]
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        _rebuild(c)
        ex = _run_1h_pass(c, _hourly(days))
        ex.assert_not_called()
        assert c.execute("SELECT 1 FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone() is not None
        ex = _run_1h_pass(c, _hourly(days, breach_after="2026-10-19 10:00"))
        assert ex.call_count == 1 and "macddiv_stop_loss" in ex.call_args.kwargs["reason"]
        assert c.execute("SELECT 1 FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone() is None


def test_missing_row_alone_still_never_triggers_a_real_sell():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        with patch("main.is_real_swing_trading_enabled", return_value=True), \
                patch("main._nse_equity_market_open_now", return_value=True), \
                patch("main._maybe_sync_real_swing_stop_loss"), \
                patch("main._maybe_place_real_swing_exit") as ex:
            main._swing_retry_refused_day.pop(SYM, None)
            main._retry_pending_real_swing_orders(c)
        ex.assert_not_called()


def test_entries_and_scan_push_the_paper_swing_mirror():
    src = inspect.getsource(main._maybe_place_real_swing_entry)
    assert src.count("_sync_signal_state_swing_external(conn)") >= 2
    assert "_sync_signal_state_swing_external(conn)" in inspect.getsource(main._run_swing_scan)
    assert "_real_off_loop(_ensure_1h_swing_state_for_orphans)" in inspect.getsource(main._scheduler_tick)


def test_entry_bar_is_last_completed_hourly_bar():
    df = main._hourly_with_str_date(_hourly(["2026-10-16"]), now_naive=pd.Timestamp("2026-10-20 09:00"))
    assert main._swing_1h_entry_bar(df, OPENED_AT) == "2026-10-16 10:15"
    assert main._swing_1h_entry_bar(df, _ist_epoch("2026-10-16 09:30")) is None
    assert main._swing_1h_entry_bar(df, 0) is None
