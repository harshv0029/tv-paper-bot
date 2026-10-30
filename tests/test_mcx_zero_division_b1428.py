"""B-1428: live /scheduler-status on 30-Oct-2026 showed last_error "GC=F: float division by zero".

Root cause: get_scheduler_capital_inr() returns 0.0 until Kotak limits() has succeeded once after a restart (the
B-1269 deploy restarted the bot at 02:12 IST, when only the MCX proxies GC=F/SI=F/CL=F are inside their open window).
_auto_signal_core built its result with round(100 * realized_today / capital, 3) for every symbol that had bars, so
capital 0.0 raised ZeroDivisionError for the whole per-symbol scan: no entry check AND no open-position management.
Once that division is guarded, a 0 daily-loss cap would read as "halted" and force-exit every open position, so
unknown capital now skips new entries only and leaves stop/target/square-off management running.

Second guard: the paper lot flooring (qty / lot_size) skips the entry on a contract row whose lot size is 0.
"""
import datetime as real_datetime
import os
import tempfile
import time
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


class _FixedUtcNow(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 5, 45, 0)  # UTC -> 11:15 IST

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _bullish_engulfing_fixture():
    base = pd.Timestamp("2026-09-09 03:45:00")
    rows = []
    for i in range(23):
        c = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        rows.append({"Date": base + pd.Timedelta(minutes=5 * i), "Open": c, "High": c + 0.1,
                     "Low": c - 0.1, "Close": c, "Volume": 1000})
    rows.append({"Date": base + pd.Timedelta(minutes=5 * 23), "Open": 101.0, "High": 101.1,
                 "Low": 99.6, "Close": 99.7, "Volume": 1000})
    rows.append({"Date": base + pd.Timedelta(minutes=5 * 24), "Open": 99.5, "High": 101.6,
                 "Low": 99.4, "Close": 101.5, "Volume": 3000})
    return pd.DataFrame(rows)


def _flat_fixture():
    """Fresh-contract / pre-first-trade shape: every bar identical, zero volume."""
    base = pd.Timestamp("2026-09-09 03:45:00")
    return pd.DataFrame([{"Date": base + pd.Timedelta(minutes=5 * i), "Open": 100.0, "High": 100.0,
                          "Low": 100.0, "Close": 100.0, "Volume": 0} for i in range(25)])


def _run(symbol="GC=F", capital=0.0, fixture=None, future=({"lot_size": 100, "underlying": "GOLDM"}, None), **kw):
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture if fixture is not None else _bullish_engulfing_fixture()), \
         patch("main.get_fx_to_inr", return_value=1.0), \
         patch("nse_fo_chain.select_nse_future", return_value=future):
        return main._auto_signal_core(symbol, capital=capital, currency="INR", strategy="bullish_engulfing",
                                      trend_sma=0, rr=10.0, **kw)


def _insert_long(symbol, entry, stop, target, qty=1.0, strategy="orb-bullish-engulfing"):
    with main.closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
            "entry_ts, fx_to_inr, interval, strategy) VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, 1.0, '5m', ?)",
            (symbol, "2026-09-09", entry, stop, stop, target, qty, time.time(), strategy))
        conn.execute("INSERT INTO positions (symbol, qty, avg_price) VALUES (?, ?, ?)", (symbol, qty, entry))
        conn.commit()


def test_capital_helpers():
    assert main._capital_known(1.0) and not main._capital_known(0.0)
    assert not main._capital_known(None) and not main._capital_known(-5) and not main._capital_known(float("nan"))
    assert main._pct_of_capital(50.0, 1000.0) == 5.0
    assert main._pct_of_capital(50.0, 0.0) is None


def test_zero_capital_no_longer_raises_and_skips_the_entry():
    """Repro of the live error: the same GC=F frame that enters at real capital raised
    ZeroDivisionError('float division by zero') at capital 0.0."""
    _fresh_db()
    result = _run(capital=0.0)
    assert result["status"] == "checked"
    assert result["action_taken"] == "skipped_capital_unavailable"
    assert result["realized_today_pct"] is None
    assert result["halted_for_day"] is False
    with main.closing(main.get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signal_state").fetchone()[0] == 0


def test_same_frame_with_real_capital_still_enters():
    _fresh_db()
    result = _run(capital=200000.0)
    assert result["action_taken"] == "entered_long"
    assert result["entry"]["risk_pct_of_capital"] is not None


def test_flat_zero_volume_frame_does_not_raise():
    _fresh_db()
    for cap in (0.0, 200000.0):
        result = _run(capital=cap, fixture=_flat_fixture())
        assert result["status"] == "checked"
        assert result["action_taken"] != "entered_long"


def test_zero_capital_open_position_stop_still_exits():
    _fresh_db()
    _insert_long("GC=F", entry=100.0, stop=101.6, target=200.0)  # last close 101.5 <= stop
    with patch("kotak_live_feed.get_live_ticks", return_value={}):
        result = _run(capital=0.0)
    assert result["action_taken"] == "exited_stop_hit"
    assert result["exit_pnl_pct"] is None


def test_zero_capital_is_not_a_daily_loss_halt_for_an_open_position():
    _fresh_db()
    _insert_long("GC=F", entry=100.0, stop=90.0, target=200.0)
    with patch("kotak_live_feed.get_live_ticks", return_value={}):
        result = _run(capital=0.0)
    assert result["action_taken"] != "exited_daily_loss_cap_hit"
    assert not str(result["action_taken"]).startswith("exited_")
    assert result["open_position"]["symbol"] == "GC=F"


def test_zero_lot_size_contract_skips_instead_of_dividing():
    _fresh_db()
    result = _run(capital=200000.0, future=({"lot_size": 0, "underlying": "GOLDM"}, None))
    assert result["action_taken"] == "skipped_no_lot_size"


def test_short_engine_zero_capital_does_not_force_cover():
    """Same halt flaw in the short engine: loss 0 >= cap 0 read as halted -> daily_loss_cap_hit cover."""
    _fresh_db()
    with main.closing(main.get_db()) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_state_short)").fetchall()}
        vals = {"symbol": "GC=F", "day": "2026-09-09", "status": "short", "entry_price": 101.4,
                "stop_loss": 150.0, "initial_stop_loss": 150.0, "target": 50.0, "qty": 1.0,
                "entry_ts": time.time(), "fx_to_inr": 1.0, "interval": "5m"}
        vals = {k: v for k, v in vals.items() if k in cols}
        conn.execute(f"INSERT INTO signal_state_short ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                     tuple(vals.values()))
        conn.commit()
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=_bullish_engulfing_fixture()), \
         patch("main.get_fx_to_inr", return_value=1.0), \
         patch("kotak_live_feed.get_live_ticks", return_value={}):
        result = main._short_signal_core("GC=F", capital=0.0, currency="INR")
    assert "daily_loss_cap" not in str(result.get("action_taken"))


def test_scheduler_scan_records_no_error_at_zero_capital():
    """End to end through the real per-symbol scan wrapper that produced the live last_error string."""
    _fresh_db()
    main._scheduler_last_error = None
    cfg = next(c for c in main.WATCHLIST if c["symbol"] == "GC=F") if any(
        c["symbol"] == "GC=F" for c in main.WATCHLIST) else {**main.NSE_STOCK_DEFAULT_PARAMS, "symbol": "GC=F"}
    cfg = {**cfg, "tz_offset_min": main.IST_OFFSET_MIN, "open_min": 9 * 60, "close_min": 23 * 60 + 30,
           "squareoff_min": 23 * 60 + 25, "currency": "INR"}
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=_bullish_engulfing_fixture()), \
         patch("main.get_fx_to_inr", return_value=1.0), \
         patch("kotak_live_feed.get_live_ticks", return_value={}):
        main._scan_equity_symbol_sync("GC=F", cfg, 0.0, 2.0, 3.0, 120.0)
    assert main._scheduler_last_error is None, main._scheduler_last_error
    assert main._scheduler_last_results["GC=F"].get("status") != "error"
