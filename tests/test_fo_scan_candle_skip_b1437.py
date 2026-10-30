"""B-1437: the 5-min option scans skip re-reading/re-evaluating a token whose COMPLETED candle set
is unchanged since its last non-firing evaluation (Render RSS 983 -> 1915 MB once the F&O universe
grew to ~2300 options). Same decisions; open positions are always managed."""
import os
import tempfile
import time
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

import kotak_fo_candle_feed as feed
import main

TOKEN = "777"
DESC = {"kind": "option", "underlying": "NIFTY", "right": "call", "strike": 25000.0,
        "expiry": "2026-10-17", "expiry_class": "weekly",
        "kotak_trading_symbol": "NIFTY17OCT2625000CE", "lot_size": 25}
UNIVERSE = {("nse_fo", TOKEN): DESC}


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old = main.DB_PATH
    main.DB_PATH = path
    main.init_db()
    main._fo_rsi2_no_signal_fp.clear()
    main._fo_strike_eval_cache.clear()
    main._fo_strike_monitor.clear()
    return old


def _add_candles(n, start_age_s=60, base=None):
    """n completed 5-min bars, the newest starting start_age_s ago (bucket-aligned not required)."""
    now = time.time() if base is None else base
    with closing(main.get_db()) as conn:
        for i in range(n):
            ts = now - start_age_s - 300 * (n - 1 - i)
            feed._persist_candle(conn, TOKEN, DESC, {"bucket_start_ts": ts, "open": 100.0, "high": 102.0,
                                                     "low": 98.0, "close": 100.0, "tick_count": 5})
        conn.commit()


def _rsi2_scan(signal=None, manage=None):
    main._fo_options_scan_last_ts = 0.0
    reader = patch("kotak_fo_candle_feed.read_fo_candles_as_df", wraps=feed.read_fo_candles_as_df)
    with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value=UNIVERSE), \
         patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
         patch("fo_option_strategy.rsi2_mean_reversion_entry_signal", return_value=signal) as ev, \
         patch("main._open_fo_option_paper_position") as opn, \
         patch("main._manage_open_fo_option_position", manage or (lambda *a, **k: None)), \
         reader as rd:
        with closing(main.get_db()) as conn:
            main._run_fo_options_scan(conn)
    return rd.call_count, ev.call_count, opn.call_count


def test_fingerprint_none_without_candles_and_tracks_appends():
    old = _db()
    try:
        assert feed.fo_candle_fingerprint(TOKEN) is None
        _add_candles(3)
        fp1 = feed.fo_candle_fingerprint(TOKEN)
        assert fp1[0] == 3
        _add_candles(1, start_age_s=0, base=time.time() + 300)
        assert feed.fo_candle_fingerprint(TOKEN)[0] == 4 and feed.fo_candle_fingerprint(TOKEN) != fp1
    finally:
        main.DB_PATH = old


def test_rsi2_unchanged_candles_not_reread_new_candle_reread():
    old = _db()
    try:
        _add_candles(210)
        assert _rsi2_scan() == (1, 1, 0)      # first pass: read + evaluate
        assert _rsi2_scan() == (0, 0, 0)      # unchanged candles: no read, same (no) decision
        _add_candles(1, start_age_s=0, base=time.time() + 300)
        assert _rsi2_scan() == (1, 1, 0)      # new completed candle: read + evaluate again
    finally:
        main.DB_PATH = old


def test_rsi2_short_history_never_read():
    old = _db()
    try:
        _add_candles(50)  # < MIN_LOOKBACK_BARS: the rule returns None on it anyway
        assert _rsi2_scan() == (0, 0, 0)
    finally:
        main.DB_PATH = old


def test_rsi2_fired_signal_is_not_cached():
    old = _db()
    try:
        _add_candles(210)
        sig = {"entry_price": 100.0, "stop_loss": 90.0}
        assert _rsi2_scan(signal=sig) == (1, 1, 1)
        assert _rsi2_scan(signal=sig) == (1, 1, 1)  # same candles, but a firing outcome is always re-evaluated
    finally:
        main.DB_PATH = old


def test_rsi2_open_position_always_managed_even_with_unchanged_candles():
    old = _db()
    try:
        _add_candles(210)
        with closing(main.get_db()) as conn:
            conn.execute(
                "INSERT INTO signal_state_fo_options (instrument_token, exchange_segment, kotak_trading_symbol, "
                "underlying, right, strike, expiry, lot_size, entry_price, initial_stop_loss, entry_bar_ts, "
                "entry_ts, day) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (TOKEN, "nse_fo", DESC["kotak_trading_symbol"], "NIFTY", "call", 25000.0, "2026-10-17", 25,
                 100.0, 90.0, "2026-10-08T05:00:00+00:00", time.time(), "2026-10-08"))
            conn.commit()
        calls = []
        for _ in range(3):
            _rsi2_scan(manage=lambda c, row, d: calls.append(row["instrument_token"]))
        assert calls == [TOKEN, TOKEN, TOKEN]
    finally:
        main.DB_PATH = old


def _strike_scan(fn):
    main._fo_strike_scan_last_ts = 0.0
    with patch("main.is_real_fo_trading_enabled", return_value=False), \
         patch("main.ist_now", return_value=datetime(2026, 10, 8, 11, 0)), \
         patch("main._is_strategy_viable_for_real_money", return_value=True), \
         patch("main._fo_strike_setup_signals", return_value=(("order_block_delta", fn),)), \
         patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value=UNIVERSE), \
         patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
         patch("main._real_fo_buy_contract") as buy, \
         patch("kotak_fo_candle_feed.read_fo_candles_as_df", wraps=feed.read_fo_candles_as_df) as rd:
        with closing(main.get_db()) as conn:
            main._run_fo_strike_setup_scan(conn)
    return rd.call_count, buy.call_count


def test_strike_unchanged_candles_replay_outcome_and_counters():
    old = _db()
    try:
        _add_candles(40)
        evals = []
        fn = lambda d: evals.append(len(d))  # returns None: no setup
        assert _strike_scan(fn) == (1, 0)
        rec = main._fo_strike_monitor[DESC["kotak_trading_symbol"]]
        assert rec["status"] == "monitored_no_setup" and rec["candles"] == 40
        shadow_before = {k: dict(v) for k, v in rec["shadow"].items()}
        assert _strike_scan(fn) == (0, 0)   # unchanged: no read, no re-evaluation
        assert evals == [40]
        rec = main._fo_strike_monitor[DESC["kotak_trading_symbol"]]
        assert rec["status"] == "monitored_no_setup" and rec["scanned"]["order_block_delta"] == 2
        for k, v in rec["shadow"].items():
            assert v["scans"] == shadow_before[k]["scans"] + 1
            assert v["signals"] == 2 * shadow_before[k]["signals"]
        _add_candles(1, start_age_s=0, base=time.time() + 300)
        assert _strike_scan(fn) == (1, 0)   # new candle -> read + evaluate
        assert evals == [40, 41]
    finally:
        main.DB_PATH = old


def test_strike_short_history_not_read_and_fired_not_cached():
    old = _db()
    try:
        _add_candles(10)
        assert _strike_scan(lambda d: None) == (0, 0)
        assert main._fo_strike_monitor[DESC["kotak_trading_symbol"]]["status"] == "warming_up_need_30_candles"
        _add_candles(30, start_age_s=0, base=time.time() + 300 * 31)
        sig = {"entry_price": 100.0, "stop_loss": 95.0}
        assert _strike_scan(lambda d: sig)[0] == 1
        assert _strike_scan(lambda d: sig)[0] == 1  # a fired setup is always re-evaluated (real switch off here)
        st = main._fo_strike_monitor[DESC["kotak_trading_symbol"]]["status"]
        assert st.startswith("setup_fired_order_block_delta")
    finally:
        main.DB_PATH = old
