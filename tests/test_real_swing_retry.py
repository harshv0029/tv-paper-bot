"""Tests for the swing real-order retry pass (2026-09-22, explicit user
instruction after the once-per-IST-day scan was found to fire outside NSE
trading hours - e.g. just after IST midnight, when a real order attempt
would fail since the exchange is closed): _nse_equity_market_open_now,
the SWING_REAL_ENTRY_PRICE_TOLERANCE_PCT gate inside
_maybe_place_real_swing_entry, and _retry_pending_real_swing_orders
itself. 2026-09-09 (used below as a fixed "now") is a Wednesday."""
import datetime as real_datetime
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _fixed_clock(now_ist: str, date="2026-09-09"):
    y, mo, d = (int(x) for x in date.split("-"))
    h, m = (int(x) for x in now_ist.split(":"))
    now_utc = real_datetime.datetime(y, mo, d, h, m, 0) - real_datetime.timedelta(minutes=main.IST_OFFSET_MIN)

    class _Fixed(real_datetime.datetime):
        _fixed = now_utc

        @classmethod
        def utcnow(cls):
            return cls._fixed
    return _Fixed


def test_market_open_true_during_session():
    with patch("main.dt.datetime", _fixed_clock("11:00")):
        assert main._nse_equity_market_open_now() is True


def test_market_open_false_before_915():
    with patch("main.dt.datetime", _fixed_clock("09:00")):
        assert main._nse_equity_market_open_now() is False


def test_market_open_false_after_1530():
    with patch("main.dt.datetime", _fixed_clock("16:00")):
        assert main._nse_equity_market_open_now() is False


def test_market_open_false_at_midnight():
    with patch("main.dt.datetime", _fixed_clock("00:05")):
        assert main._nse_equity_market_open_now() is False


def test_market_open_false_on_weekend():
    # 2026-09-12 is a Saturday.
    with patch("main.dt.datetime", _fixed_clock("11:00", date="2026-09-12")):
        assert main._nse_equity_market_open_now() is False


def _entry_patches(ltp=100.0, entry_ok=True):
    return [
        patch("kotak_live_feed.get_live_ticks",
              return_value={"TESTSTOCK.NS": {"ltp": ltp, "trading_symbol": "TESTSTOCK-EQ"}}),
        patch("main.get_scheduler_capital_inr", return_value=1_000_000.0),
        patch("main._real_today_spent_inr", return_value=0.0),
        patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}),
        patch("kotak_real_orders.place_real_entry",
              return_value={"ok": entry_ok, "qty": 10, "fill_price": ltp, "order_id": "E1",
                            "fill_price_confirmed": True, "detail": "rejected"}),
        patch("kotak_real_orders.place_real_stop_loss",
              return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}),
    ]


def test_entry_within_tolerance_proceeds():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = _entry_patches(ltp=101.5)  # 1.5% above entry_price=100.0
    started = [p.start() for p in patches]
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        for p in patches:
            p.stop()


def test_entry_beyond_tolerance_skipped():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = _entry_patches(ltp=105.0)  # 5% above entry_price=100.0, beyond the 2% band
    started = [p.start() for p in patches]
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is None
            attempt = conn.execute(
                "SELECT * FROM real_trades WHERE symbol = 'TESTSTOCK.NS' AND status = 'skipped_price_out_of_tolerance'"
            ).fetchone()
            assert attempt is not None
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        for p in patches:
            p.stop()


def _insert_paper_swing_position(conn, symbol, entry_day, entry_price=100.0, stop_loss=90.0, qty=10):
    conn.execute(
        "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, "
        "initial_stop_loss, gap_low, qty, entry_ts, fx_to_inr) VALUES (?, 'gap_and_go', ?, ?, ?, ?, ?, ?, 1.0)",
        (symbol, entry_day, entry_price, stop_loss, entry_price - 1, qty, main.time.time()),
    )
    conn.commit()


class TestRetryPendingRealSwingOrders:
    def test_noop_when_gate_off(self):
        _fresh_db()
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        with closing(main.get_db()) as conn:
            _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-09")
            with patch("main.dt.datetime", _fixed_clock("11:00")), \
                 patch("main._maybe_place_real_swing_entry") as mock_entry:
                main._retry_pending_real_swing_orders(conn)
                mock_entry.assert_not_called()

    def test_noop_when_market_closed(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-09")
                with patch("main.dt.datetime", _fixed_clock("00:05")), \
                     patch("main._maybe_place_real_swing_entry") as mock_entry:
                    main._retry_pending_real_swing_orders(conn)
                    mock_entry.assert_not_called()
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_retries_pending_entry_from_today_during_market_hours(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-09", entry_price=100.0)
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_place_real_swing_entry") as mock_entry:
                    main._retry_pending_real_swing_orders(conn)
                    mock_entry.assert_called_once_with(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "gap_and_go")
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_skips_pending_entry_from_a_prior_day(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-08")  # yesterday
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_place_real_swing_entry") as mock_entry:
                    main._retry_pending_real_swing_orders(conn)
                    mock_entry.assert_not_called()
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_skips_entry_already_mirrored_real(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-09")
                conn.execute(
                    "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
                    "entry_order_id, opened_at, day, stop_loss, strategy) "
                    "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-09', 90.0, 'gap_and_go')",
                    (main.time.time(),),
                )
                conn.commit()
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_place_real_swing_entry") as mock_entry:
                    main._retry_pending_real_swing_orders(conn)
                    mock_entry.assert_not_called()
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_retries_pending_exit_when_paper_already_closed(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                # Real position open, but no matching paper row - paper
                # already exited and deleted its row before the real
                # mirror could complete.
                conn.execute(
                    "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
                    "entry_order_id, opened_at, day, stop_loss, strategy) "
                    "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-08', 90.0, 'gap_and_go')",
                    (main.time.time(),),
                )
                conn.commit()
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_place_real_swing_exit") as mock_exit:
                    main._retry_pending_real_swing_orders(conn)
                    mock_exit.assert_called_once_with(conn, "TESTSTOCK.NS")
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_skips_exit_retry_when_paper_still_open(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                _insert_paper_swing_position(conn, "TESTSTOCK.NS", "2026-09-08")
                conn.execute(
                    "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
                    "entry_order_id, opened_at, day, stop_loss, strategy) "
                    "VALUES ('TESTSTOCK.NS', 'TESTSTOCK-EQ', 10, 100.0, 'E1', ?, '2026-09-08', 90.0, 'gap_and_go')",
                    (main.time.time(),),
                )
                conn.commit()
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_place_real_swing_exit") as mock_exit:
                    main._retry_pending_real_swing_orders(conn)
                    mock_exit.assert_not_called()
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)

    def test_also_runs_sl_sync_pass(self):
        _fresh_db()
        os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
        try:
            with closing(main.get_db()) as conn:
                with patch("main.dt.datetime", _fixed_clock("11:00")), \
                     patch("main._maybe_sync_real_swing_stop_loss") as mock_sl:
                    main._retry_pending_real_swing_orders(conn)
                    mock_sl.assert_called_once_with(conn)
        finally:
            os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
