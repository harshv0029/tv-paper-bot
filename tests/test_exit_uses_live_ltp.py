"""Tests for exit decisions (target_hit/stop_hit) and the recorded fill
price using live LTP instead of the last closed candle (2026-09-17,
explicit user instruction "Candle-close lag - replace this", extending
the trailing-stop-only fix in test_trailing_stop_live_ltp.py to the exit
checks themselves - see _auto_signal_core's own `exit_price` comment for
the full reasoning). Mirrors test_trend_weakened_range_exclusion.py's
fixture/patching pattern."""
import math
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _insert_open_position(conn, symbol: str, entry_price=100.0, stop_loss=90.0, target=130.0):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
        "VALUES (?, ?, 'long', ?, ?, ?, ?, 10, ?, 1.0, '5m')",
        (symbol, _fixed_ist_day_str(), entry_price, stop_loss, stop_loss, target, main.time.time()),
    )
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, ?, 'buy', 10, ?, 1.0, 'test-universal-score', '{}')",
        (main.time.time(), symbol, entry_price),
    )
    conn.commit()


class _FixedUtcNow(__import__("datetime").datetime):
    _fixed = __import__("datetime").datetime(2026, 9, 14, 5, 0, 0)  # UTC -> 10:30 IST

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _fixed_ist_day_str() -> str:
    ist = _FixedUtcNow._fixed + __import__("datetime").timedelta(minutes=main.IST_OFFSET_MIN)
    return ist.strftime("%Y-%m-%d")


def _flat_fixture(last_close: float, days: int = 5, bars_per_day: int = 20) -> pd.DataFrame:
    """A flat/mildly-noisy series whose LAST close is exactly `last_close` -
    kept strictly between stop (90) and target (130) in every test here, so
    the OLD candle-close-only logic would see no exit at all; only the live
    tick (patched separately) should be able to trigger one."""
    rows = []
    i = 0
    base_dates = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-14"]
    n_total = days * bars_per_day
    for day in base_dates[:days]:
        base = pd.Timestamp(f"{day} 03:45:00")  # UTC -> 09:15 IST
        for b in range(bars_per_day):
            ts = base + pd.Timedelta(minutes=5 * b)
            frac = i / max(n_total - 1, 1)
            close = 100 + frac * (last_close - 100) + 0.05 * math.sin(i / 2.0)
            rows.append({
                "Date": ts, "Open": close, "High": close + 0.2, "Low": close - 0.2,
                "Close": close, "Volume": 1000 + (i % 10) * 10,
            })
            i += 1
    rows[-1]["Close"] = last_close  # pin the exact last close the test asserts against
    return pd.DataFrame(rows)


def _run_tick(symbol: str, last_close: float, live_ticks: dict):
    fixture = _flat_fixture(last_close)
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("main._trend_confidence", return_value=0.0), \
         patch("kotak_live_feed.get_live_ticks", return_value=live_ticks):
        return main._auto_signal_core(symbol, currency="INR")


def test_stop_hit_fires_on_live_price_even_though_last_close_has_not_crossed():
    _fresh_db()
    symbol = "LIVESTOP.NS"
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, symbol, entry_price=100.0, stop_loss=90.0, target=130.0)
    # last closed candle is 105 (well inside stop/target) - old logic: no exit.
    # live tick is 89, BELOW the 90 stop.
    result = _run_tick(symbol, last_close=105.0, live_ticks={symbol: {"ltp": 89.0}})
    assert result["action_taken"] == "exited_stop_hit"
    assert result["exit_pnl_inr"] == (89.0 - 100.0) * 10


def test_target_hit_fires_on_live_price_and_records_live_fill():
    _fresh_db()
    symbol = "LIVETARGET.NS"
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, symbol, entry_price=100.0, stop_loss=90.0, target=130.0)
    # last closed candle is 105 (below target) - old logic: no exit.
    # live tick is 135, ABOVE the 130 target.
    result = _run_tick(symbol, last_close=105.0, live_ticks={symbol: {"ltp": 135.0}})
    assert result["action_taken"] == "exited_target_hit"
    assert result["exit_pnl_inr"] == (135.0 - 100.0) * 10


def test_no_live_tick_falls_back_to_last_close_exit_decision_unchanged():
    _fresh_db()
    symbol = "NOLIVETICK.NS"
    with closing(main.get_db()) as conn:
        _insert_open_position(conn, symbol, entry_price=100.0, stop_loss=90.0, target=130.0)
    # No live tick for this symbol at all - must behave exactly like the
    # pre-existing candle-close-only logic: last_close=105 is inside
    # stop/target, so no exit.
    result = _run_tick(symbol, last_close=105.0, live_ticks={})
    assert result["action_taken"] not in ("exited_stop_hit", "exited_target_hit")
