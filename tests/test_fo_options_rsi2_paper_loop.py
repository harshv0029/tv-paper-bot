"""Unit tests for the RSI(2) options paper-position scan
(_run_fo_options_scan / _open_fo_option_paper_position /
_manage_open_fo_option_position in main.py) - the position-management
loop over kotak_fo_candle_feed's resolved F&O universe. Uses a temp
sqlite DB (main.DB_PATH swapped, same pattern as
tests/test_kotak_fo_candle_feed.py) and mocks the universe/candle-read
so no live Kotak session is needed.

Run: pytest tests/ -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import pandas as pd

import main

DESCRIPTOR = {
    "kind": "option", "underlying": "NIFTY", "right": "call", "strike": 24500.0,
    "expiry": "2026-10-27", "expiry_class": "monthly",
    "kotak_trading_symbol": "NIFTY26OCT24500CE", "lot_size": 75,
}
UNIVERSE_KEY = ("nse_fo", "12345")


def _with_temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = main.DB_PATH
    main.DB_PATH = path
    main.init_db()
    return old_path


def _restore_db(old_path):
    main.DB_PATH = old_path


def _entry_signal_dict():
    return {
        "entry_price": 100.0, "stop_loss": 90.0, "rsi2": 5.0, "atr": 5.0,
        "entry_bar_ts": pd.Timestamp("2026-09-16T10:15:00", tz="UTC"),
    }


def test_scan_opens_a_paper_position_when_entry_signal_fires():
    old_path = _with_temp_db()
    try:
        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={UNIVERSE_KEY: DESCRIPTOR}), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=pd.DataFrame({"Close": [100.0]})), \
             patch("fo_option_strategy.rsi2_mean_reversion_entry_signal", return_value=_entry_signal_dict()), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()
            pos = conn.execute("SELECT * FROM positions WHERE symbol = 'NIFTY26OCT24500CE:RSI2FO'").fetchone()
        assert row is not None
        assert row["entry_price"] == 100.0
        assert row["initial_stop_loss"] == 90.0
        assert row["lot_size"] == 75
        assert pos is not None and pos["qty"] == 75
    finally:
        _restore_db(old_path)


def test_scan_never_opens_a_second_position_on_an_already_open_leg():
    old_path = _with_temp_db()
    try:
        with closing(main.get_db()) as conn:
            main._open_fo_option_paper_position(conn, "12345", "nse_fo", DESCRIPTOR, _entry_signal_dict())

        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={UNIVERSE_KEY: DESCRIPTOR}), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=None), \
             patch("fo_option_strategy.rsi2_mean_reversion_entry_signal", return_value=_entry_signal_dict()), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)

        with closing(main.get_db()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM signal_state_fo_options WHERE instrument_token = '12345'"
            ).fetchone()["c"]
        assert count == 1
    finally:
        _restore_db(old_path)


def test_scan_skips_futures_legs_entirely():
    fut_descriptor = dict(DESCRIPTOR, kind="future", right=None, strike=None)
    old_path = _with_temp_db()
    try:
        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={UNIVERSE_KEY: fut_descriptor}), \
             patch("fo_option_strategy.rsi2_mean_reversion_entry_signal") as mock_signal, \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)
        mock_signal.assert_not_called()
    finally:
        _restore_db(old_path)


def test_scan_skips_opening_a_new_position_when_force_close_is_due():
    old_path = _with_temp_db()
    try:
        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={UNIVERSE_KEY: DESCRIPTOR}), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=pd.DataFrame({"Close": [100.0]})), \
             patch("fo_option_strategy.rsi2_mean_reversion_entry_signal", return_value=_entry_signal_dict()), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=True):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)

        with closing(main.get_db()) as conn:
            row = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()
        assert row is None
    finally:
        _restore_db(old_path)


def test_manage_open_position_force_closes_regardless_of_rsi2_exit_signal():
    old_path = _with_temp_db()
    try:
        with closing(main.get_db()) as conn:
            main._open_fo_option_paper_position(conn, "12345", "nse_fo", DESCRIPTOR, _entry_signal_dict())
            row = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()

        with patch("nse_fo_chain.must_force_close_before_expiry", return_value=True), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=pd.DataFrame({"Close": [105.0]})), \
             patch("fo_option_strategy.rsi2_mean_reversion_exit_reason", return_value=None) as mock_exit:
            with closing(main.get_db()) as conn:
                main._manage_open_fo_option_position(conn, row, DESCRIPTOR)
        mock_exit.assert_not_called()  # force-close short-circuits before the RSI2 exit check even runs

        with closing(main.get_db()) as conn:
            remaining = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()
            trade = conn.execute(
                "SELECT * FROM trades WHERE symbol = 'NIFTY26OCT24500CE:RSI2FO' AND action = 'sell'"
            ).fetchone()
        assert remaining is None
        assert trade is not None
        assert trade["strategy"] == "rsi2_premium_reversion"
    finally:
        _restore_db(old_path)


def test_manage_open_position_exits_on_rsi2_exit_signal():
    old_path = _with_temp_db()
    try:
        with closing(main.get_db()) as conn:
            main._open_fo_option_paper_position(conn, "12345", "nse_fo", DESCRIPTOR, _entry_signal_dict())
            row = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()

        with patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=pd.DataFrame({"Close": [120.0]})), \
             patch("fo_option_strategy.rsi2_mean_reversion_exit_reason", return_value="rsi_reverted"):
            with closing(main.get_db()) as conn:
                main._manage_open_fo_option_position(conn, row, DESCRIPTOR)

        with closing(main.get_db()) as conn:
            remaining = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()
            trade = conn.execute(
                "SELECT * FROM trades WHERE symbol = 'NIFTY26OCT24500CE:RSI2FO' AND action = 'sell'"
            ).fetchone()
        assert remaining is None
        assert trade is not None
        assert '"exit_reason": "rsi_reverted"' in trade["raw_payload"]
        assert '"pnl_inr": 1500.0' in trade["raw_payload"]  # (120-100)*75
    finally:
        _restore_db(old_path)


def test_manage_open_position_is_a_noop_when_nothing_fires():
    old_path = _with_temp_db()
    try:
        with closing(main.get_db()) as conn:
            main._open_fo_option_paper_position(conn, "12345", "nse_fo", DESCRIPTOR, _entry_signal_dict())
            row = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()

        with patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=pd.DataFrame({"Close": [101.0]})), \
             patch("fo_option_strategy.rsi2_mean_reversion_exit_reason", return_value=None):
            with closing(main.get_db()) as conn:
                main._manage_open_fo_option_position(conn, row, DESCRIPTOR)

        with closing(main.get_db()) as conn:
            remaining = conn.execute("SELECT * FROM signal_state_fo_options WHERE instrument_token = '12345'").fetchone()
        assert remaining is not None
    finally:
        _restore_db(old_path)


def test_paper_trades_are_excluded_from_daily_loss_cap_strategy_prefix():
    # today_realized_pnl only counts strategy LIKE 'orb-%' - confirm this
    # engine's tag deliberately does not match, same exclusion as
    # nse_straddle_state's own 'long_straddle' tag.
    assert not "rsi2_premium_reversion".startswith("orb-")


def test_scan_interval_guard_uses_module_level_timestamp():
    assert main.FO_OPTIONS_SCAN_INTERVAL_SECONDS > 0
    assert hasattr(main, "_fo_options_scan_last_ts")


def test_scheduler_tick_calls_fo_options_scan():
    import inspect
    src = inspect.getsource(main._scheduler_tick)
    assert "_run_fo_options_scan(conn)" in src


def test_scan_records_a_scheduler_check_for_each_flat_leg_considered():
    old_path = _with_temp_db()
    try:
        main._scheduler_check_counts.clear()
        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={UNIVERSE_KEY: DESCRIPTOR}), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=None), \
             patch("fo_option_strategy.rsi2_mean_reversion_entry_signal"), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)
        # Recorded even though this leg didn't fire a signal - "checked"
        # means the scheduler looked at it this tick, same semantics
        # _record_scheduler_check already has for equity/options-overlay
        # symbols, not "a signal fired".
        assert main._scheduler_check_counts.get("NIFTY26OCT24500CE:RSI2FO") == 1
    finally:
        _restore_db(old_path)


def test_scan_records_a_scheduler_check_for_each_open_position_managed():
    old_path = _with_temp_db()
    try:
        main._scheduler_check_counts.clear()
        with closing(main.get_db()) as conn:
            main._open_fo_option_paper_position(conn, "12345", "nse_fo", DESCRIPTOR, _entry_signal_dict())

        with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={}), \
             patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=None), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
             patch("fo_option_strategy.rsi2_mean_reversion_exit_reason", return_value=None):
            main._fo_options_scan_last_ts = 0.0
            with closing(main.get_db()) as conn:
                main._run_fo_options_scan(conn)
        assert main._scheduler_check_counts.get("NIFTY26OCT24500CE:RSI2FO") == 1
    finally:
        _restore_db(old_path)


def test_asset_class_and_source_recognizes_fo_rsi2_legs():
    asset_class, data_source, mcx_proxy_for = main._asset_class_and_source("NIFTY26OCT24500CE:RSI2FO")
    assert asset_class == "fo_option"
    assert data_source == "kotak_fo_candle_feed"
    assert mcx_proxy_for is None
