"""Option trail peak also uses the tick-built feed candle high (catches spikes between 30s polls)."""
import time
from contextlib import closing
from unittest.mock import patch

import main
import kotak_fo_candle_feed as kfc
from tests.test_real_option_trailing_sl import _db, _insert, _state


def _candle(conn, ts, high):
    conn.execute(
        "INSERT INTO fo_option_candles (instrument_token, kotak_trading_symbol, underlying, kind, right, strike, expiry, "
        "bucket_start_ts, open, high, low, close, tick_count) VALUES ('999','S','NIFTY','option','put',25000,'2026-10-17',?,100,?,99,100,5)",
        (ts, high))
    conn.commit()


def _run(conn, ltp):
    with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state()), \
         patch("main._option_ltp", return_value=ltp), \
         patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
         patch("main.kotak_real_orders_closing_session", return_value=False), \
         patch("kotak_real_fo_orders.ensure_option_trailing_sl",
               side_effect=lambda s, e, q, d, l: {"ok": True, "action": "placed", "order_id": "S", "trigger_price": d}) as ens:
        main._sync_real_fo_option_sl(conn, "NIFTY:PUT")
        return ens.call_args[0][3]


def test_feed_candle_high_since_entry_raises_peak_and_trigger():
    _db(); kfc._in_progress_candles.clear()
    with closing(main.get_db()) as conn:
        opened = time.time() - 600
        _insert(conn, opened=opened, trig=None, peak=100.0)
        _candle(conn, opened + 60, 130.0)
        assert abs(_run(conn, 105.0) - 130.0 * 0.99) < 1e-6
        assert conn.execute("SELECT peak_price FROM real_fo_positions").fetchone()[0] == 130.0


def test_pre_entry_candle_is_ignored():
    _db(); kfc._in_progress_candles.clear()
    with closing(main.get_db()) as conn:
        opened = time.time() - 600
        _insert(conn, opened=opened, trig=None, peak=100.0)
        _candle(conn, opened - 300, 200.0)
        assert abs(_run(conn, 100.0) - 97.0) < 1e-6


def test_in_progress_candle_counts_and_no_feed_falls_back_to_ltp():
    _db(); kfc._in_progress_candles.clear()
    with closing(main.get_db()) as conn:
        opened = time.time() - 600
        _insert(conn, opened=opened, trig=None, peak=100.0)
        assert abs(_run(conn, 120.0) - 120.0 * 0.99) < 1e-6
        kfc._in_progress_candles["999"] = {"bucket_start_ts": opened + 120, "high": 150.0}
        assert abs(_run(conn, 120.0) - 150.0 * 0.99) < 1e-6
    kfc._in_progress_candles.clear()
